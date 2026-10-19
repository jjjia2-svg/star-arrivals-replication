"""`pipeline/` is a port of the author's original data-collection code (the private
`multiplex_pipeline/` and `v2_output/` trees), changed only by a short, explicitly listed set of
path-resolution hunks.

The byte-for-byte comparison against those private sources ran in the author's private repository
and is not part of this package. What runs here, with no private tree present:
  1. the symbolic proof - every PATCHED or RECOVERED file, with the port's path substitutions undone
     and machine paths folded to fixed tokens, must hash to the value recorded in
     `tests/pipeline_symbolic.sha256` (recorded where the sources were present);
  2. the byte manifest - every file under `pipeline/` must match `tests/pipeline_ported.sha256`;
  3. the repo-authored pins, the launcher registrations, the path-guard identity pins and the write
     barrier checks below;
  4. no file under `pipeline/` contains a machine-specific absolute path.
"""
import hashlib
import pathlib
import re
import sys
import difflib
import warnings

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths  # noqa: E402

SOURCE = load_paths()["legacy_multiplex"]   # private; absent on a replicator's machine

#: port counts against the private original code (measured, and checked, in the author's private
#: repository): files with a legacy counterpart, how many of those are byte-identical, how many are
#: PATCHED. pipeline/README.md states them and tests/test_pipeline_rebuild.py keeps the two in step.
N_WITH_COUNTERPART, N_IDENTICAL, N_PATCHED = 421, 391, 30

SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_FILES = {".DS_Store"}

# Files inside the ported tree with no legacy counterpart.
#
# T2-review F1: this list is now EMPTY, and that is the fix. It used to hold one auto-executed
# `pipeline/units/conftest.py` (the test-path bridge). Locks on *entry* into ADDED were not enough:
# the reviewer appended a payload to the file that was ALREADY exempted - rewriting the signed
# `star.percentile_primary` and converting every failing report to passed - for one file edit plus
# one sha256 re-pin, with all three suites green. Content pinning cannot win that race, because the
# same edit that adds the payload updates the pin.
#
# So the exemption was removed rather than hardened: the nine `*/tests` directories now go on
# sys.path from `pytest.ini`'s `pythonpath`, which lives in this repo's ordinary review surface and
# is not executed as code. `pipeline/` therefore contains no auto-executed file that lacks a legacy
# counterpart, and the locks below have nothing left to except.
#
# repo-relative path -> (sha256 of the REPO file, why it exists)
ADDED: dict[str, tuple[str, str]] = {}

#: basenames CPython or pytest executes without anybody importing them by name
AUTO_EXECUTED_BASENAMES = ("conftest.py", "sitecustomize.py", "usercustomize.py", "__init__.py")
AUTO_EXECUTED_SUFFIXES = (".pth",)

#: the separately-declared escape hatch, deliberately empty. Anything put here is announced on every
#: run AND has to move the count below in the same commit.
AUTO_EXECUTED_EXEMPTIONS: dict[str, str] = {}
N_AUTO_EXECUTED_EXEMPTIONS = 0

# The ledger, pinned so prose and code cannot drift apart again (T1-review F2 corrected 389/377).
# T2 adds the 6 driver files (4 verbatim + 2 patched); ADDED went 1 -> 0 in the fix wave.
# T4 adds the 2 FWCI scripts, both patched (each holds absolute paths and nothing else moved).
# T5 adds the 4 roster scripts: 3 patched (one absolute-path line each) + 70_prep_fnfix
# verbatim (it holds no absolute path at all).
# T6 adds the 11 stars scripts: 4 patched (run_screening, 60, 72, 00_make_u4_aug - each holds one
# or two absolute-path constants) + 7 verbatim (screening_lib and 61/71/73/74/75/76 hold none;
# 61 and 75 read the API key out of ~/.zshrc through expanduser, which is not a literal path).
# T7 adds the 7 frame builders: 6 patched (each holds two to ten absolute-path constants) +
# 60_lb_tau.py verbatim (it derives everything from its own __file__ and holds none).
# cal2026-08-28 T3 adds 10_build_union_frame_gold.py, patched (eleven absolute-path constants).
N_WITH_COUNTERPART, N_IDENTICAL, N_PATCHED = 421, 391, 30
#: every tracked file under pipeline/, hashed in tests/pipeline_ported.sha256 (T6 final NIT-4)
#: cal2026-08-28: 480 -> 485, the five repo-authored files of pipeline/stars/caliber_2026-08-28/
#: cal T4: 491 -> 492, run_cal_estimates.py; cal T5: 492 -> 493, run_cal_cloud.py
#: cal T6: 493 -> 494, run_cal_ledger.py
#: cal2026-10 aws (2026-09-22): 494 -> 499, the five repo-authored files of pipeline/aws/cal2026-10/
#: (manifested then without moving this count — the manifest at 89d1ecf holds 499 lines)
#: cal2026-10 (2026-09-23): 499 -> 531, the 32 repo-authored files of pipeline/frames/cal2026-10/**,
#: pipeline/rosters/cal2026-10/ and pipeline/stars/caliber_2026-10/ (the count tools/verify_ported.py
#: --write printed after their registration in REPO_AUTHORED; == `git ls-files pipeline | wc -l`)
N_PORTED_MANIFEST = 578

# Machine-specific path markers (a macOS home directory or a mounted volume). Each marker is split
# so this detector is not itself a hit for the repository-wide scan it enforces.
_HOME_ROOT = "/" + "Users"
ABS = re.compile(_HOME_ROOT + r"/[A-Za-z0-9._-]+/|/" + "Volumes/")
# --- normalise-and-compare: the invariant --------------------------------------------------------
# T1 re-review (F8/F9). The previous guard classified each introduced line by SHAPE. That proved a
# line *is a path expression*; it never proved it is *the same path*, and it exempted rows inside
# multi-line strings - where `run_u4._STAR_CELL_SQL`, the sole production star-identification query,
# lives. Three smuggles walked through: an inserted SQL predicate, a swapped real dataset directory,
# and a swapped resolver. No shape rule closes that class.
#
# What replaces it is a complete proof rather than a heuristic. Take the ported file, undo the port
# mechanically - delete the preamble BLOCKS, substitute every resolver expression and documentation
# placeholder back to the value it resolves to on this machine - and require the result to be
# BYTE-IDENTICAL to the legacy source. Anything the port did that was not one of those substitutions
# survives normalisation and shows up as a byte difference, wherever in the file it hides.
#
# The substitution rules are GENERIC (applied to every patched file, never per-file), so the rule
# table itself cannot carry a per-file exception. The values come from config/paths.yaml, so this
# file holds no absolute path.

# T6 review MAJOR-2 (new). These used to be THIS MACHINE's resolved values, which made the whole
# proof machine-bound: on any configuration where `ssd_root` disagreed with the paths baked into the
# legacy bytes - i.e. on every replicator's machine - `needs_matching_ssd_root` skipped BOTH layers,
# and a reviewer's silent `and aage >= 2` inside `72_restake_fnfix_stars.py` passed the entire
# verbatim suite (55 passed / 55 skipped, 0 failures). The definition of a star sat behind a skip.
#
# The fix is to stop using this machine at all. What the proof needs is the literal the LEGACY bytes
# carry, because the claim being checked is "undoing the port's substitutions reproduces the legacy
# file" - and that literal is discoverable from the legacy tree itself:
#
#   * the SSD root comes out of the legacy `common/preflight.py`'s own `DATA_ROOT` constant;
#   * the thesis root is the path the legacy files are being READ from, so it is correct by
#     construction;
#   * the author's home is the first two components of that thesis path.
#
# Nothing here is machine-specific any more, so the two layers run wherever the legacy tree does.
# The separate claim "the resolvers resolve to those same values ON THIS MACHINE" is a different
# property, checked by tests/test_paths.py's pinned values where the private trees exist.
def _legacy_ssd_root() -> pathlib.Path:
    """The data-disk root baked into the legacy bytes, read out of the legacy tree."""
    probe = SOURCE / "units/u0_foundation/src/common/preflight.py"
    if probe.is_file():
        m = re.search(r'DATA_ROOT: str = "([^"]+)"', probe.read_text(encoding="utf-8"))
        if m:
            return pathlib.Path(m.group(1).rstrip("/")).parent          # .../<ssd>/derived -> <ssd>
    return load_paths()["ssd_root"]                                      # legacy tree absent


_LEGACY_SSD = _legacy_ssd_root()
_D = str(_LEGACY_SSD / "derived")
_S = str(_LEGACY_SSD / "snapshot")
_SSD = str(_LEGACY_SSD)
_T = str(load_paths()["legacy_thesis"])
_MOUNT = str(_LEGACY_SSD.parent)
_HOME = (re.match("(" + _HOME_ROOT + r"/[^/]+)", _T).group(1)
         if re.match("(" + _HOME_ROOT + r"/[^/]+)", _T) else str(pathlib.Path.home()))

# The three preamble blocks the port may introduce, verbatim. Removal is block-wise, not line-wise:
# a lone preamble line (or an edited one) is NOT deleted, so it cannot be used as a hiding place.
_PRE_HEAD = ("# --- M3 port: repo path resolution (legacy hard-coded the author's machine)"
             " \u2014 config/paths.yaml ---\n")
_PRE_BODY_UNITS = ('import pathlib as _sar_pl, sys as _sar_sys\n'
                   '_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents'
                   ' if p.name == "units").parents[1]\n')
_PRE_BODY_ROOT = ('import sys as _sar_sys\n'
                  '_sar_repo = pathlib.Path(__file__).resolve().parents[1]\n')
_PRE_TAIL = ('if str(_sar_repo) not in _sar_sys.path:\n'
             '    _sar_sys.path.append(str(_sar_repo))\n')
# T2: a file that needs more than one resolver carries ONE block importing the whole set, rather
# than one block per name. The import tail is a single fixed literal and is paired with EITHER
# repo-anchor body, so it is not a per-file rule: `pipeline/drivers/<run>/<file>.py` counts parents,
# `pipeline/units/<u>/src/.../<file>.py` walks up to the directory named `units`.
_PRE_BODY_DRIVERS = ('import pathlib as _sar_pl, sys as _sar_sys\n'
                     '_sar_repo = _sar_pl.Path(__file__).resolve().parents[3]\n')
# T4: the same NAMED-anchor shape as the units body, for the layer directory the FWCI run
# directories sit in. It is `.resolve()`d, so it still finds the repo when the file is executed
# through the symlink `pipeline/fwci/run_fwci.py` stages into a scratch run directory.
_PRE_BODY_FWCI = ('import pathlib as _sar_pl, sys as _sar_sys\n'
                  '_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents'
                  ' if p.name == "fwci").parents[1]\n')
# T5: the same NAMED-anchor shape again, for the rosters layer. It has to survive relocation:
# `run_rosters.py` hard-links 00b/00c into a staging mirror under `<repo>/output/rosters/<stage>/`,
# where the FIRST ancestor named "rosters" is `<repo>/output/rosters` and `.parents[1]` is still the
# repo. The launcher asserts that property before it stages anything, so a moved scratch root fails
# loudly instead of importing nothing.
_PRE_BODY_ROSTERS = ('import pathlib as _sar_pl, sys as _sar_sys\n'
                     '_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents'
                     ' if p.name == "rosters").parents[1]\n')
# T6: the same NAMED-anchor shape once more, for the stars layer. `run_stars.py` hard-links the
# ported script into `<repo>/output/stars/<run dir>/code/`, where the first ancestor named "stars"
# is `<repo>/output/stars` and `.parents[1]` is still the repo - the run_fwci arrangement exactly.
_PRE_BODY_STARS = ('import pathlib as _sar_pl, sys as _sar_sys\n'
                   '_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents'
                   ' if p.name == "stars").parents[1]\n')
_PRE_IMPORT_ALL = (
    "from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402,F401\n"
    "                                snapshot_root as _sar_snapshot_root,\n"
    "                                ssd_root as _sar_ssd_root,\n"
    "                                legacy_thesis as _sar_legacy_thesis,\n"
    "                                require_readable as _sar_rd,\n"
    "                                require_writable as _sar_rw,\n"
    "                                output_target as _sar_out,\n"
    "                                deferred_output_target as _sar_lazyout)\n"
)
# T5: the ALL set plus `staged_run_dir`, for a ported script whose ONE absolute constant is both its
# input root and its output root (see pipeline/lib/paths.py). Written out rather than derived from
# the block above, because a preamble literal is compared byte for byte.
_PRE_IMPORT_ALL_STAGED = (
    "from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402,F401\n"
    "                                snapshot_root as _sar_snapshot_root,\n"
    "                                ssd_root as _sar_ssd_root,\n"
    "                                legacy_thesis as _sar_legacy_thesis,\n"
    "                                require_readable as _sar_rd,\n"
    "                                require_writable as _sar_rw,\n"
    "                                output_target as _sar_out,\n"
    "                                deferred_output_target as _sar_lazyout,\n"
    "                                staged_run_dir as _sar_staged)\n"
)
# T7: the same NAMED-anchor shape for the frames layer. `run_frames.py` hard-links the ported
# builder into `<repo>/output/frames/<run dir>/code/`, where the first ancestor named "frames" is
# `<repo>/output/frames` and `.parents[1]` is still the repo - run_fwci/run_stars exactly.
_PRE_BODY_FRAMES = ('import pathlib as _sar_pl, sys as _sar_sys\n'
                    '_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents'
                    ' if p.name == "frames").parents[1]\n')
_PRE_DRIVERS = _PRE_HEAD + _PRE_BODY_DRIVERS + _PRE_TAIL + _PRE_IMPORT_ALL
_PRE_UNITS_MULTI = _PRE_HEAD + _PRE_BODY_UNITS + _PRE_TAIL + _PRE_IMPORT_ALL
_PRE_FWCI_MULTI = _PRE_HEAD + _PRE_BODY_FWCI + _PRE_TAIL + _PRE_IMPORT_ALL
_PRE_ROSTERS_STAGED = _PRE_HEAD + _PRE_BODY_ROSTERS + _PRE_TAIL + _PRE_IMPORT_ALL_STAGED
_PRE_STARS_MULTI = _PRE_HEAD + _PRE_BODY_STARS + _PRE_TAIL + _PRE_IMPORT_ALL
_PRE_STARS_STAGED = _PRE_HEAD + _PRE_BODY_STARS + _PRE_TAIL + _PRE_IMPORT_ALL_STAGED
_PRE_FRAMES_MULTI = _PRE_HEAD + _PRE_BODY_FRAMES + _PRE_TAIL + _PRE_IMPORT_ALL
_PRE_FRAMES_STAGED = _PRE_HEAD + _PRE_BODY_FRAMES + _PRE_TAIL + _PRE_IMPORT_ALL_STAGED
PREAMBLE_BLOCKS = tuple(
    _PRE_HEAD + body + _PRE_TAIL + f"from pipeline.lib.paths import {fn} as _sar_{fn}  # noqa: E402\n"
    for body in (_PRE_BODY_UNITS, _PRE_BODY_ROOT, _PRE_BODY_FWCI)
    for fn in ("derived_root", "snapshot_root")
) + (_PRE_DRIVERS, _PRE_UNITS_MULTI, _PRE_FWCI_MULTI, _PRE_ROSTERS_STAGED,
     _PRE_STARS_MULTI, _PRE_STARS_STAGED, _PRE_FRAMES_MULTI, _PRE_FRAMES_STAGED)

# T2 / residual R3: the drivers wrap their resolved roots in the read/write guards. A guard call is
# NOT a path expression of its own - normalisation removes the wrapper and whatever is inside still
# has to fold back to the legacy literal, so the wrapper cannot carry a payload. Every one takes
# exactly one argument, which is what makes that removal unambiguous.
#   _sar_rd / _sar_rw   require_readable / require_writable - the root must be usable
#   _sar_out            output_target          - refuse NOW if the destination is legacy or frozen
#   _sar_lazyout        deferred_output_target - refuse at the first WRITE (shared module; T2-rev F3)
#   _sar_staged         staged_run_dir         - relocate a run directory that is BOTH the script's
#                                                input root and its output root; refuses when no
#                                                launcher staged one, so the legacy directory is
#                                                never returned (T5)
GUARD_CALLS = ("_sar_rd(", "_sar_rw(", "_sar_out(", "_sar_lazyout(", "_sar_staged(")


def _guard_span(text: str, k: int, guard: str) -> int:
    """End index (exclusive) of the guard call that starts at `k`, by balanced-paren matching."""
    depth, i = 1, k + len(guard)
    while depth:
        assert i < len(text), f"unbalanced {guard} - the port is malformed"
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        i += 1
    return i


def _strip_guards(text: str) -> str:
    """`_sar_rw(X)` -> `X`. Multi-line and nested wrappers both work."""
    for guard in GUARD_CALLS:
        while True:
            k = text.find(guard)
            if k < 0:
                break
            i = _guard_span(text, k, guard)
            text = text[:k] + text[k + len(guard):i - 1] + text[i:]
    return text


def _guard_free(text: str) -> str:
    """`text` with every declared path-resolution preamble block removed - the block names the
    guards in its import list, which would otherwise be counted as uses."""
    for _blk in PREAMBLE_BLOCKS:
        text = text.replace(_blk, "")
    return text


def _guarded_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges covered by a guard call. Used to prove every resolver sits inside one -
    a span check, not a line check, because a wrapped expression spans lines (T2-review F3)."""
    spans = []
    for guard in GUARD_CALLS:
        start = 0
        while True:
            k = text.find(guard, start)
            if k < 0:
                break
            spans.append((k, _guard_span(text, k, guard)))
            start = k + len(guard)
    return spans

# Resolver expressions -> the literal each one reproduces. Order matters: longest form first.
SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    # T7 (rule A). Half the frame builders' absolute paths sit inside f-strings that ALSO carry a
    # real placeholder (`{VAR}`, `{FIELD}`, `{tag}`), because `02_clone_chain.py` machine-generated
    # them by textual substitution. Those literals cannot be folded into `str(R() / "...")` without
    # losing the placeholder, so the port replaces the ROOT PREFIX ONLY and the f-string survives as
    # an f-string. The token is a fixed string mapping to a fixed value, exactly like every other
    # rule here, and it must come first: the bare `_sar_legacy_thesis()` rule below would otherwise
    # rewrite the inside of the braces into `pathlib.Path(...)`.
    ('{_sar_derived_root()}', _D),
    ('{_sar_snapshot_root()}', _S),
    ('{_sar_ssd_root()}', _SSD),
    ('{_sar_legacy_thesis()}', _T),
    ('str(_sar_derived_root()) + "/"', f'"{_D}/"'),
    ('str(_sar_snapshot_root()) + "/"', f'"{_S}/"'),
    ('str(_sar_ssd_root()) + "/"', f'"{_SSD}/"'),
    ('str(_sar_legacy_thesis()) + "/"', f'"{_T}/"'),
    ('str(_sar_derived_root() / "', f'"{_D}/'),      # closing `")` handled by CLOSERS below
    ('str(_sar_snapshot_root() / "', f'"{_S}/'),
    ('str(_sar_ssd_root() / "', f'"{_SSD}/'),
    ('str(_sar_legacy_thesis() / "', f'"{_T}/'),      # T5
    ('_sar_derived_root() / "', f'pathlib.Path("{_D}/'),
    ('_sar_snapshot_root() / "', f'pathlib.Path("{_S}/'),
    ('_sar_ssd_root() / "', f'pathlib.Path("{_SSD}/'),
    ('str(_sar_derived_root())', f'"{_D}"'),
    ('str(_sar_snapshot_root())', f'"{_S}"'),
    ('str(_sar_ssd_root())', f'"{_SSD}"'),
    ('str(_sar_legacy_thesis())', f'"{_T}"'),
    ('_sar_derived_root()', f'pathlib.Path("{_D}")'),
    ('_sar_snapshot_root()', f'pathlib.Path("{_S}")'),
    ('_sar_ssd_root()', f'pathlib.Path("{_SSD}")'),
    ('_sar_legacy_thesis()', f'pathlib.Path("{_T}")'),
    # documentation placeholders (docstrings and .md), each a single reversible token. The names are
    # deliberately unlike anything the legacy prose uses - the first draft used `<derived_root>`,
    # which the guard caught colliding with a real docstring in legacy run_u4.py line 693.
    ("<SAR_DERIVED_ROOT>", _D),
    ("<SAR_SSD_MOUNT>", _MOUNT),
    ("<SAR_HOME>", _HOME),
)
# `str(X / "a/b")` and `X / "a/b"` leave one surplus `)` once the call is folded into a literal.
CLOSERS = (('str(_sar_derived_root() / "', '")', _D), ('str(_sar_snapshot_root() / "', '")', _S),
           ('str(_sar_ssd_root() / "', '")', _SSD), ('str(_sar_legacy_thesis() / "', '")', _T),
           ('_sar_derived_root() / "', '"', _D), ('_sar_snapshot_root() / "', '"', _S),
           ('_sar_ssd_root() / "', '"', _SSD))


#: T7 (rule B). The one shape rule A cannot reach: a legacy PLAIN string literal with an absolute
#: path EMBEDDED in it (`con.execute("SET temp_directory='<abs>'")`). The port has to interpolate,
#: which turns the literal into an f-string - so folding the placeholder back must also drop the `f`
#: prefix, or the two files differ by one character. The rule is generic and total: the f-string must
#: have EXACTLY one placeholder, that placeholder must be a resolver joined with a string literal and
#: nothing else, and the text either side of it must be brace-free. Anything else the port did
#: survives normalisation, which is the property the whole proof rests on.
FSTRING_JOIN = re.compile(
    r'f"([^"{}]*)\{(_sar_derived_root|_sar_snapshot_root|_sar_ssd_root|_sar_legacy_thesis)\(\)'
    r' / "([^"{}]*)"\}([^"{}]*)"')
_FSTRING_ROOTS = {"_sar_derived_root": _D, "_sar_snapshot_root": _S,
                  "_sar_ssd_root": _SSD, "_sar_legacy_thesis": _T}


def _fold_fstring_joins(text: str) -> str:
    return FSTRING_JOIN.sub(
        lambda m: f'"{m.group(1)}{_FSTRING_ROOTS[m.group(2)]}/{m.group(3)}{m.group(4)}"', text)


def _normalise(text: str) -> str:
    """Undo the port: drop whole preamble blocks, then fold every resolver call back to the literal
    it resolves to on this machine. Anything else the port changed survives and will not match."""
    for block in PREAMBLE_BLOCKS:
        text = text.replace(block + "\n", "").replace(block, "")
    text = _strip_guards(text)
    text = _fold_fstring_joins(text)          # rule B, before the CLOSERS pass sees the inner quote
    # fold `str(R() / "x")` -> `"<val>/x"` and `R() / "x"` -> `pathlib.Path("<val>/x")`
    for opener, closer, root in CLOSERS:
        out, i = [], 0
        while True:
            k = text.find(opener, i)
            if k < 0:
                out.append(text[i:]); break
            end_q = text.index('"', k + len(opener))
            inner = text[k + len(opener):end_q]
            after = text[end_q:end_q + len(closer)]
            assert after == closer, f"unexpected close {after!r} after {opener!r}"
            folded = f'"{root}/{inner}"' if opener.startswith("str(") \
                else f'pathlib.Path("{root}/{inner}")'
            out.append(text[i:k]); out.append(folded)
            i = end_q + len(closer)
        text = "".join(out)
    for src, dst in SUBSTITUTIONS:
        if src.endswith('/ "'):
            continue                      # already handled by the CLOSERS pass
        text = text.replace(src, dst)
    return text


# repo-relative path -> (sha256 of the LEGACY source, how many preamble BLOCKS the port injected,
# why this file could not stay verbatim). The block count is declared, not derived from the file, so
# an extra injected preamble block - which normalisation would otherwise delete and thus hide -
# fails loudly (T1 re-review, attack 9).
PATCHED: dict[str, tuple[str, int, str]] = {
    "pipeline/units/u0_foundation/src/common/preflight.py": (
        "af1df8d201ce23e30edc5e0f2af1e374df43dc760a86795179d8e3fa74f4eed4",
        1,
        "DATA_ROOT constant was the author's SSD derived dir -> derived_root() from config/paths.yaml",
    ),
    "pipeline/units/u0p5_dept_roster/src/roster/run_u0p5.py": (
        "1f8bb4d2d3a87c9119490e88cc1e8d7b818f2b698869fff93cf2889f965f32c5",
        1,
        "SSD_DERIVED_DIR / U1_FULL_DIR / two person_map literals + module docstring -> derived_root(); "
        "SSD_DERIVED_DIR additionally goes through deferred_output_target - it is a live CLI whose "
        "write root is the FROZEN, non-empty <derived>/u0p5_roster (T2 re-review R3). The read roots "
        "stay unguarded on purpose: require_readable raises at IMPORT, and T1 measured that requiring "
        "the disk at import makes the 2,001-test ported suite uncollectable (15 collection errors); "
        "deferred_output_target never raises at import, which is why the write root can be guarded",
    ),
    "pipeline/units/u0p5_dept_roster/README.md": (
        "e6f0078a3b20d979db12ab4945ce23642d98af7cbd18429350088b6e7c3098e0",
        0,
        "doc line naming the author's SSD output path -> <derived_root> placeholder",
    ),
    "pipeline/units/u1_fetch/src/m0_snapshot/s3_sync.py": (
        "b07cddab57e49dd5b7d03d69978e6309fb2e2d00639e6c794dca378ab77a24a3",
        0,
        "docstring naming the author's SSD mount -> <ssd_root> placeholder (no code change)",
    ),
    "pipeline/units/u1_fetch/tests/test_s3_sync.py": (
        "a4a6cffd621ee950ffe2a7d85a88344bffdcc9303469f066a35fd8909529bc8c",
        1,
        "snapshot_root= test argument -> snapshot_root(); the assertions are unchanged and the\n"
        "        SSD_ROOT_LEAF guard keeps the substring one of them matches on",
    ),
    "pipeline/units/u1_fetch/tests/test_stream_build.py": (
        "131f1ed05a83f144319646c536dd797bf806654346bb0538b507b924c5633347",
        1,
        "_REAL_SHARD skipif guard for the @slow real-shard smoke -> snapshot_root() from config",
    ),
    "pipeline/units/u4_output_star/src/run_u4.py": (
        "a0ba2537f0853e631e9e61fde7ad37f1991c0a9186886b8e00db22aa6a926666",
        1,
        "STOCK_ASOF_NOTE['measurement_artifact'] pointer -> derived_root() (same string when "
        "ssd_root is configured as documented, so the frozen manifest header is unchanged)",
    ),
    "pipeline/units/u4_output_star/tests/test_roster_v3_wiring.py": (
        "34dc0114dea66fc00a3bf558d4ac1e3553859032dae575b97f0962ce3fded4ad",
        1,
        "guarded real-data test's registry_v3 dir and derived root -> derived_root() from config",
    ),
    "pipeline/units/u5_dose/run_u5.py": (
        "a04a54df27235bb4260cdda7230fe09b12bfdd397b40eba67fedbc8b60c045fb",
        1,
        "DEFAULT_DATA_ROOT argparse default -> derived_root() from config/paths.yaml",
    ),
    "pipeline/units/u6_assemble/run_u6.py": (
        "1c4bed880054c40710f1c3a49baed93a6507605788935e8b45bc6466a838db4a",
        1,
        "DEFAULT_DATA_ROOT argparse default -> derived_root() from config/paths.yaml",
    ),
    "pipeline/units/u6_assemble/README.md": (
        "917d8486310ef17c7c2e5f36471627119186e4d732c22a8c5860d532451c383c",
        0,
        "doc invocation naming the author's interpreter and SSD out-root -> placeholders",
    ),
    "pipeline/run_smoke_m1.py": (
        "c25c8f44adfb8af70ac161c51c48b9b5e85072dafe552987820b1db9f5dc749a",
        1,
        "DEFAULT_SNAPSHOT_ROOT + its docstring line -> snapshot_root() from config/paths.yaml",
    ),
    # --- T2 drivers ---------------------------------------------------------------------------
    "pipeline/drivers/final80_p10_2026-07-22/common80.py": (
        "875903b4ad0fc858704b69bc7303f64b1f97eca6cde6e782e7a438d69fbe7e1e",
        1,
        "SSD (the derived root every U4/U5/U6 output hangs off) -> require_writable(derived_root()); "
        "R_PKG (step4's R-export destination) -> deferred_output_target(legacy_thesis()/...), the "
        "write barrier: str() still reports the legacy destination, the first write refuses "
        "(T2-review F3). The third absolute path in this file, DRAFT37_CSV, is a DELETED "
        "/private/tmp input and is left verbatim - see LOST_INPUTS",
    ),
    "pipeline/drivers/u3_run/run_u3_rebuild_f123_2026-07-06.py": (
        "899fc42ca914c80f122cc1f0e25acc0ca4d9262cc1a0fd1eb6e59c71f9442038",
        1,
        "SNAPSHOT/DATA_ROOT -> require_readable(snapshot_root()/ssd_root()/...); OUT -> "
        "output_target(require_writable(derived_root())/...), which refuses at import because the "
        "destination is a FROZEN artifact of the original run (T2-review F5). The build_panel call, "
        "resume=False included, is untouched",
    ),
    # --- T4 FWCI (source tree: v2_output, not multiplex_pipeline) -------------------------------
    "pipeline/fwci/fwci_baseline_fullsnapshot_2026-08-09/code/01_scan_full_snapshot.py": (
        "508b645af8ac9c7c1459654866395a206dfbf04426f8cf442c01f2730ebcbea9",
        1,
        "ROOT (the legacy thesis tree the u0/u1 production modules are imported from) and SNAPSHOT "
        "(the 696 GB OpenAlex snapshot) -> require_readable(legacy_thesis()/snapshot_root()). Both "
        "are READ locations, so the guard is require_readable and it raises at import: this script "
        "is the 36-minute full-snapshot scan and cannot do anything useful without the disk. Its "
        "OUTPUT location is not patchable - PARTIAL_DIR/DATA_DIR/LOG_DIR hang off "
        "`BASE = Path(__file__).resolve().parent.parent`, a line holding no absolute path - so the "
        "destination is moved the way step3's was: from outside, by the launcher",
    ),
    "pipeline/fwci/fwci_fullsnapshot_rebuild_2026-08-09/code/01_build_expected_full.py": (
        "23bb44769d68566aded6a746fc4c03be1371afbd6ebf0a2116caa649924e9002",
        1,
        "ROOT (the legacy thesis tree holding the full-snapshot pop table and the u0/u4 production "
        "modules) and OLDPOP (the 514 MB pre-rebuild denominator on the data disk) -> "
        "require_readable(legacy_thesis()/derived_root()). Both are reads. OUT/OUT_OLD/OUT_JSON "
        "hang off `BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`, which holds "
        "no absolute path and therefore may not be touched; pipeline/fwci/run_fwci.py stages a run "
        "directory through output_target() instead",
    ),
    # --- T5 rosters (source tree: v2_output) ----------------------------------------------------
    # All three carry the SAME shape of defect and therefore the same hunk: one absolute constant
    # that is at once the script's input root and its output root. `output_target()` cannot help
    # (it judges a destination, and it treats a non-empty directory as frozen - which a staging
    # mirror must be), so the constant goes through `staged_run_dir()`: with no staged root it
    # refuses, and with one it returns the launcher's mirror. Nothing else in any of the three moves.
    "pipeline/rosters/multidisc_roster_econ_grade_2026-08-09/verify/merge_chemmath_verified_v2.py": (
        "2982cff03ec0dcbdd3145218ad9dfa7dae161f0e26952cef460ae91f0bb23f93",
        1,
        "BASE, the single constant every read AND every write in this script hangs off (61+13+5 "
        "verified batch directories and the two match CSVs in, six outputs including the frozen "
        "roster_clean_chemmath_verified.parquet out) -> staged_run_dir(legacy_thesis()/...). The "
        "script also re-creates verify/_backup_pre_gapfill_2026-08-10 and rewrites "
        "rejected_persons_chemmath.csv, so an in-place re-run would overwrite the 2026-08-10 "
        "evidence in the read-only legacy tree",
    ),
    "pipeline/rosters/multidisc_gold_2026-08-10/code/00b_prep_roster_variants.py": (
        "0e683a52fe5e5fa385d79cede35383908d665bdf342391fec3de8bc5ccaaae04",
        1,
        "ROOT -> staged_run_dir(legacy_thesis()). Its OUT is `dirname(dirname(__file__))/data`, a "
        "line holding no absolute path and therefore untouchable, so run_rosters.py hard-links the "
        "script into the same mirror ROOT resolves to - the run_fwci.py move-the-file pattern and "
        "the resolve-the-constant pattern combined, because this script needs both",
    ),
    "pipeline/rosters/multidisc_gold_2026-08-10/code/00c_prep_final_population.py": (
        "2c2828c97f2d41b3f526022de793756c98f70e9c6641feee802235146b390fdd",
        1,
        "ROOT -> staged_run_dir(legacy_thesis()). Everything it reads (the centre roster, the lost "
        "incfel base, the signed final event tables) and its OUT = f'{G}/data/final' are all "
        "derived from ROOT in lines that hold no absolute path, so relocating ROOT relocates the "
        "whole stage and nothing else is touched",
    ),
    # --- T6 stars (source tree: v2_output) ------------------------------------------------------
    "pipeline/stars/multidisc_2026-07-24/code/star_screening/run_screening.py": (
        "e8805aad24c070d3afe1f21f6098b9bb8ad4d1239bea170c83e4c609e888f4d8",
        1,
        "BASE (the 2026-07-24 run directory: its silver roster in, its shortlist CSV and screening "
        "report out) -> deferred_output_target(...), and SSD (the 24 GB u1 edge tables the ranking "
        "pool is built from) -> require_readable(derived_root()/...). BASE uses the DEFERRED "
        "barrier, not output_target: this module is imported for its `_POOL_SQL` by the 60 and 72 "
        "stages, and a barrier that raised at import would take the ranking machine down with it. "
        "Reads through BASE still resolve, writes refuse. The third absolute path in this file, "
        "SCRATCH, is a deleted /private/tmp session directory used only as DuckDB's temp dir and is "
        "left verbatim - see LOST_INPUTS",
    ),
    "pipeline/stars/multidisc_gold_2026-08-10/code/60_poach_gate_false_negatives.py": (
        "87366e78c11a465227d2bbf4ccb813fd3007da518d3117f24df227dcfc6a850a",
        1,
        "ROOT (the legacy thesis tree holding the three rosters and the 79-event ledger this script "
        "reads) and SSD -> require_readable(legacy_thesis()/derived_root()/...). Both are READS. "
        "Its OUT hangs off `BASE = dirname(dirname(abspath(__file__)))`, a line with no absolute "
        "path and therefore untouchable, so run_stars.py stages the run directory instead. Note "
        "that SCREEN, the sys.path entry it imports the ranking machine from, still names the "
        "legacy tree - that line holds no absolute path of its own either, so the launcher "
        "pre-imports the REPO's run_screening/screening_lib and the insert becomes inert",
    ),
    "pipeline/stars/multidisc_gold_2026-08-10/code/72_restake_fnfix_stars.py": (
        "8c39b7136e5e8da34b26ccaca1f4cdb724eda0b868d746ac923775e6ec157ce0",
        1,
        "identical shape to 60: ROOT and SSD -> require_readable(...), output through the staged run "
        "directory, SCREEN handled by the launcher's pre-import. This is the script whose re-run "
        "reproduces the frozen 67-row fnfix_restake_2026-08-15.csv byte for byte",
    ),
    "pipeline/stars/econ_fnfix_2026-08-15/code/00_make_u4_aug.py": (
        "84cfd6a515b72307eb98a66fdde2482d089ca8a16580e033f1c4b2d4da8f00fe",
        1,
        "ROOT (the re-stake CSV and the econ_p10 config it reads) -> require_readable(legacy_thesis"
        "()) and U4 (the frozen 2026-07-22 star set on the data disk) -> "
        "require_readable(derived_root()/...). BASE is __file__-derived and untouchable, so the "
        "launcher stages the run directory and links data/new_events_econ.csv in. The version "
        "ported is the file on disk, and the ruling is in pipeline/stars/README.md: a replay of the "
        "author's recorded edits reproduces it byte for byte, and the one post-run edit adds a "
        "single line AFTER both pq.write_table calls that touches only the config dict",
    ),
    # --- T7 frames ------------------------------------------------------------------------------
    # Two shapes here that no earlier task met, both a consequence of `02_clone_chain.py` having
    # machine-generated these builders by textual substitution: (a) absolute paths FULLY EXPANDED
    # inside f-strings that also carry a real placeholder - rule A folds the root prefix and the
    # f-string stays an f-string; (b) three to five separate absolute WRITE destinations per script,
    # which output_target()'s single-use $SAR_OUT_ROOT redirect cannot hold, so every write goes
    # through staged_run_dir()'s T7 generalisation instead. `60_lb_tau.py` needed neither and is
    # byte-identical.
    "pipeline/frames/econ_fnfix_2026-08-15/code/01_merge_inputs.py": (
        "1cecd13e7ed0e7991e2b53d9cf5de4f643d134ff0a57347180b91012ee95dc60",
        1,
        "ROOT (the 79-event ledger and the 52-event frame it merges) -> require_readable("
        "legacy_thesis()). Its BASE is __file__-derived and untouchable, so run_frames.py stages the "
        "run directory and links the three inputs in; the OpenAlex branch is skipped because the "
        "2026-08-15 supplement JSONL is one of them (H11)",
    ),
    "pipeline/frames/econ_fnfix_2026-08-15/code/04_rebuild_y.py": (
        "1d54d7b93eebe94ccd92562f00b1735d53ab8ec4ba532c4ac56ec892476f15b5",
        1,
        "the P1 econ frame builder: ROOT + SSD -> require_readable(legacy_thesis()/derived_root()); "
        "five READ constants (FRAME_DIR/FRAME_IN/PATCH_A/UNITS + the new-events CSV) resolved "
        "through legacy_thesis(); two WRITE destinations (OUT_JSON and the per-variant out_path) "
        "through staged_run_dir(). It reads and writes the SAME legacy run directory, which is why "
        "the reads stay pointed at the legacy tree and only the writes are relocated",
    ),
    "pipeline/frames/econ_fnfix_2026-08-15/code/10_panels23_econ920.py": (
        "7458243764ed2d4a8eb608c1b6dd359c76385b813668f7b8d743b810a85c270c",
        1,
        "the P2 econ becoming panel + the 663 MB pairs_unified.csv: ROOT + SSD guarded, three READ "
        "constants (PATCH_A/REL/SUP_FNFIX) resolved, and all THREE writes (becoming_unified.csv, "
        "pairs_unified.csv, panels23_report.json) staged. Three writes in one script is the case "
        "output_target() cannot serve - its redirect refuses a root the first write just filled",
    ),
    "pipeline/frames/multidisc_gold_2026-08-10/code/20_rebuild_y_gold.py": (
        "dc5db53054764980384698d8f8421a16a1b43aa1f7bca8de61f0dbcfe9efa39f",
        1,
        "the P1 chem/math frame builder: ROOT + SSD guarded; EXP_NEW and five f-string READ paths "
        "resolved (rule A); the DuckDB temp directory and the two writes staged. Its `SET "
        "temp_directory` line is the one place a legacy PLAIN literal has an absolute path embedded "
        "mid-string, which is what rule B exists for",
    ),
    "pipeline/frames/multidisc_gold_2026-08-10/code/30_build_panels23_gold.py": (
        "2d1933dbc60c3f1978bdebc2aef9e581984ac028c410be299fbef382627f19f6",
        1,
        "the P2 chem/math becoming panel + pairs_none.parquet + the legacy slim: ROOT + SSD guarded, "
        "six f-string READ paths resolved, and OUT + TMP staged. OUT is the directory every one of "
        "its five outputs hangs off, so staging that one constant relocates the whole write side",
    ),
    "pipeline/frames/multidisc_gold_2026-08-10/code/10_build_union_frame_gold.py": (
        "073ecc85cf90bbe7d848c2c333184969f1b818fcd34260c7d7cdbc83f7e2a1b0",
        1,
        "cal2026-08-28 T3: the union-frame builder (gold stage 2/4 - dept channel x events, dose, "
        "age-gap guard, relationships table). ROOT + SSD guarded, seven f-string READ paths "
        "resolved (rule A), and OUT_DIR - the directory all four outputs hang off - staged. Its "
        "BASE-relative reads (the two events_gold CSVs, _duck_tmp) are linked in by run_frames.py",
    ),
    "pipeline/frames/p3_topicpair_2026-08-17/code/50_leftbehind_build.py": (
        "ea6c89f396a28ed24156cb52010cb9e983d236bc5b56a10bd3156c0fcc813c3f",
        1,
        "the FIVE-cell leftbehind build - the A_far cell of which is the paper's Panel 3, and the "
        "whole of which is what writes data/frames/p3_afar_counts.csv. One hunk: V, the v2_output "
        "root it reads all nine inputs from. Its BASE is __file__-derived, so run_frames.py stages "
        "the run directory and every write lands in the mirror",
    ),
}

# --- T2: absolute paths the port deliberately did NOT resolve ------------------------------------
# A path that names a location which no longer exists cannot be "resolved" - pointing it anywhere
# would fabricate provenance. It stays verbatim and is declared here instead. The repo-wide
# absolute-path scan does not see it (it matches neither half of the ABS detector above), so this
# ledger plus its test is what keeps it visible.
LOST_INPUTS: dict[str, tuple[str, str]] = {
    "pipeline/drivers/final80_p10_2026-07-22/common80.py": (
        "/private/tmp/",
        "DRAFT37_CSV = new_stars_COMBINED_p10_2026-07-22.csv, the 65-row combined star shortlist "
        "step1 reads. It lived in a deleted per-session /private/tmp directory (plan D2-ii), so "
        "step1 can never rerun; the artifact it produced is frozen on the SSD and its star rows "
        "are in data/raw_verified/. Registered in pipeline/drivers/README.md.",
    ),
    "pipeline/stars/multidisc_2026-07-24/code/star_screening/run_screening.py": (
        "/private/tmp/",
        "SCRATCH, the DuckDB temp directory `_con()` creates. It names a per-session "
        "/private/tmp working directory the OS reclaimed long ago. It is not an "
        "input and holds no artifact - repointing it would fabricate nothing, but it would also be "
        "a change to a line that is not path RESOLUTION (the location no longer exists on any "
        "machine), so it stays verbatim and is declared here instead. `_con()` is reached only from "
        "this module's own main(), which run_stars.py declares NOT_RUNNABLE; the 60/72 stages "
        "import the module for _POOL_SQL and never call it.",
    ),
    "pipeline/stars/multidisc_gold_2026-08-10/code/00_build_candidates_restake_econ_u4flagged9.py": (
        "/private/tmp/",
        "the temporary task output under /private/tmp this rung reads its four non-literal "
        "U4-flagged verdicts from. The FILE is gone (the temporary directory was reclaimed) and the "
        "path stays verbatim because repointing it would fabricate provenance - but the CONTENT is "
        "NOT lost: it survives in the author's private working records, is frozen in this package "
        "as data/stage_payloads/u4_star_events.json, and run_stars.py writes it back here for the "
        "duration of the stage, then removes it. With it the rung runs and the frozen 67-row "
        "fnfix_candidates_restake.csv AND the 9-row poach_fn_recheck_econ_U4flagged9_2026-08-16.csv "
        "both rebuild byte for byte.",
    ),
}

# --- T2-review F4: inputs a ported driver READS that nothing on disk PRODUCES --------------------
# Distinct from LOST_INPUTS (a dead path in the code). These are live paths to artifacts that exist,
# are read by the ported step1, and whose builder does not exist in any tree. The review measured
# that both were mis-attributed in the first draft of drivers/README.md to skipped-but-present
# driver directories that only READ them.
# constant in the ported file -> (the file, what a replicator can check instead)
NO_PRODUCER_INPUTS: dict[str, tuple[str, str]] = {
    "ROSTER_V4_PROJ8": (
        "pipeline/drivers/final80_p10_2026-07-22/common80.py",
        "<derived>/u5u6_final_2026-07-18_work/roster_v4_proj8/dept_roster_panel_{monash,unsw}.parquet "
        "- the Monash/UNSW half of step1's colleague pool. All eight references to the name in the "
        "legacy trees READ it; u5u6_final_2026-07-18/step1_freeze_ship_u4.py writes "
        "u4_star_set_11school_2026-07-16, not this. It is an 8-column projection of "
        "u0p5_roster/roster_v4_2026-07-16 (both 180 rows, 10 columns -> 8, hence 'proj8') made by a "
        "step that was never archived. Check instead: row count 180 against roster_v4_2026-07-16, "
        "and that the 8 columns are a subset of the 10.",
    ),
    "ADELAIDE_MERGED": (
        "pipeline/drivers/final80_p10_2026-07-22/common80.py",
        "<derived>/u0p5_roster/adelaide_backfill_2007_2021_2026-07-20/"
        "dept_roster_panel_adelaide_MERGED_209plus_gapfill.parquet - the colleague-pool authority "
        "for the 5 Adelaide gap events of 79. Nothing in either legacy tree writes it; the "
        "u0p5_expand_adelaide scripts are all 2026-07-11 and never mention backfill/gapfill/209plus. "
        "Its own MANIFEST.json describes an ad-hoc Wayback-CDX crawl with hand-applied employment "
        "gates. Check instead: the MANIFEST.json beside it, and that exactly the 5 "
        "ADELAIDE_GAP_EVENT_IDS depend on it.",
    ),
}

# --- T2 / residual R3: which ported driver file must wire the path guards ------------------------
# T6 FINAL review MAJOR-3: this used to be a tuple of PATHS, i.e. it pinned *that* a guard is wired
# and never *which*. The reviewer swapped one token in `00_select_new_events_econ.py` -
# `_sar_staged(` -> `_sar_rd(` - and all three verbatim layers passed: the span still contains a
# resolver, so the new wrapper rule is satisfied; `_strip_guards` deletes both tokens identically,
# so normalisation folds back to the replay; and the hunk sanity rule sees a source line that DID
# carry an absolute path. Only the sha manifest objected, and that is a visibility aid a `--write`
# in the same commit clears. The consequence is the T2-review F3 step4 incident reintroduced by one
# token: `_sar_rd(...)` returns the legacy directory itself, so the script's
# `open(f"{E}/data/new_events_econ.csv", "w")` would land on the frozen artifact.
#
# The guard IDENTITY is the safety policy - `_sar_rd` = "must be readable", `_sar_rw` = "must be
# writable", `_sar_out`/`_sar_lazyout` = "refuse a legacy or frozen destination", `_sar_staged` =
# "must be a launcher-staged mirror, never the legacy directory" - so it is what gets pinned. The
# declaration is the exact multiset of guard tokens each file's body uses, outside the preamble.
# repo-relative path -> ("<guard>x<count>", …), sorted
GUARDED_DRIVERS: dict[str, tuple[str, ...]] = {
    "pipeline/drivers/final80_p10_2026-07-22/common80.py":
        ("_sar_lazyout(x1", "_sar_rw(x1"),
    "pipeline/drivers/u3_run/run_u3_rebuild_f123_2026-07-06.py":
        ("_sar_out(x1", "_sar_rd(x2", "_sar_rw(x1"),
    # T5: the three roster scripts resolve exactly one root each, and it is a READ-AND-WRITE root,
    # so the guard is `staged_run_dir` and it raises at import when no launcher staged a mirror.
    "pipeline/rosters/multidisc_roster_econ_grade_2026-08-09/verify/merge_chemmath_verified_v2.py":
        ("_sar_staged(x1",),
    "pipeline/rosters/multidisc_gold_2026-08-10/code/00b_prep_roster_variants.py":
        ("_sar_staged(x1",),
    "pipeline/rosters/multidisc_gold_2026-08-10/code/00c_prep_final_population.py":
        ("_sar_staged(x1",),
    # the three recovered producers resolve their roots the same way
    "pipeline/rosters/econ_roster_verify_2026-08-09/code/merge_roster.py":
        ("_sar_staged(x1",),
    "pipeline/rosters/econ_roster_verify_2026-08-09/code/build_audit.py":
        ("_sar_rd(x2", "_sar_staged(x1"),
    "pipeline/rosters/multidisc_gold_2026-08-10/code/00b2_prep_incfel_variant.py":
        ("_sar_staged(x1",),
    # T4: the two FWCI scripts resolve read roots only, and both guards raise at IMPORT. That is
    # deliberate here and the opposite of run_u0p5's rule: these are standalone scripts run through
    # a launcher, not modules the 2,001-test ported suite has to be able to collect.
    "pipeline/fwci/fwci_baseline_fullsnapshot_2026-08-09/code/01_scan_full_snapshot.py":
        ("_sar_rd(x2",),
    "pipeline/fwci/fwci_fullsnapshot_rebuild_2026-08-09/code/01_build_expected_full.py":
        ("_sar_rd(x2",),
    # T6: run_screening's BASE is a read-AND-write root, so its guard is the DEFERRED barrier (it
    # must stay importable - 60 and 72 import it for _POOL_SQL); the other three resolve read roots
    # only and raise at import without the data disk.
    "pipeline/stars/multidisc_2026-07-24/code/star_screening/run_screening.py":
        ("_sar_lazyout(x1", "_sar_rd(x1"),
    "pipeline/stars/multidisc_gold_2026-08-10/code/60_poach_gate_false_negatives.py":
        ("_sar_rd(x2",),
    "pipeline/stars/multidisc_gold_2026-08-10/code/72_restake_fnfix_stars.py":
        ("_sar_rd(x2",),
    "pipeline/stars/econ_fnfix_2026-08-15/code/00_make_u4_aug.py":
        ("_sar_rd(x2",),
    # MAJOR-3's subject: `E` is the run directory this script WRITES into. `_sar_staged` is the only
    # correct guard for it - `_sar_rd` would hand back the legacy directory and the write would land
    # on the frozen artifact.
    "pipeline/stars/multidisc_gold_2026-08-10/code/00_select_new_events_econ.py":
        ("_sar_staged(x1",),
    # --- T7 frames layer (added by the M3 milestone review, port-fidelity MAJOR) ------------------
    # These five were the gap: T6's review wrote the policy down ("a file whose declared destination
    # is a read-and-write legacy run directory must use `_sar_staged`") and T7 then added five files
    # of exactly that shape without extending the pin. The reviewer swapped `_sar_staged(` for
    # `_sar_rd(` in `10_panels23_econ920.py`, and REMOVED the guard entirely from
    # `30_build_panels23_gold.py`, and both passed all 274 verbatim tests and both sha manifests -
    # and the second one then really did overwrite frozen artifacts in the read-only legacy tree.
    # The completeness assertion below is the actual fix; these entries are what it now has to check.
    "pipeline/frames/econ_fnfix_2026-08-15/code/01_merge_inputs.py":
        ("_sar_rd(x1",),
    "pipeline/frames/econ_fnfix_2026-08-15/code/04_rebuild_y.py":
        ("_sar_rd(x2", "_sar_staged(x2"),
    "pipeline/frames/econ_fnfix_2026-08-15/code/10_panels23_econ920.py":
        ("_sar_rd(x2", "_sar_staged(x3"),
    "pipeline/frames/multidisc_gold_2026-08-10/code/20_rebuild_y_gold.py":
        ("_sar_rd(x2", "_sar_staged(x4"),
    "pipeline/frames/multidisc_gold_2026-08-10/code/30_build_panels23_gold.py":
        ("_sar_rd(x2", "_sar_staged(x2"),
    "pipeline/frames/multidisc_gold_2026-08-10/code/10_build_union_frame_gold.py":
        ("_sar_rd(x2", "_sar_staged(x1"),
    # the Panel-3 builder made NO guard call at all until the milestone review; its `V` resolver was
    # bare, so `refuse_unstaged_in_place_run()` never fired for it.
    "pipeline/frames/p3_topicpair_2026-08-17/code/50_leftbehind_build.py":
        ("_sar_rd(x1",),
}

#: files that use a guard but are deliberately NOT in `GUARDED_DRIVERS`, each with the dedicated pin
#: that covers it instead. An exemption is a declaration, so it has to name what replaces the pin.
GUARD_PIN_EXEMPT: dict[str, str] = {
    "pipeline/units/u0p5_dept_roster/src/roster/run_u0p5.py":
        "has its own dedicated identity pin, test_run_u0p5_write_root_is_behind_the_barrier, which "
        "asserts the exact `_sar_lazyout(_sar_derived_root() / \"u0p5_roster\")` token AND that "
        "`_sar_rd(` is absent - a stronger claim than a multiset, because the ABSENCE of the read "
        "guard is the property that keeps the 2,001-test ported suite collectable without the disk",
}


def guard_multiset(rel: str) -> tuple[str, ...]:
    """The multiset of guard tokens `rel`'s body uses, outside the declared preamble blocks."""
    body = _guard_free((REPO / rel).read_text(encoding="utf-8"))
    return tuple(sorted(f"{g}x{body.count(g)}" for g in GUARD_CALLS if body.count(g)))


def guard_using_files() -> set[str]:
    """Every ported or recovered file that calls a guard at all - derived, never listed."""
    return {rel for rel in (set(PATCHED) | set(RECOVERED)) if guard_multiset(rel)}

#: the resolver calls that MUST be wrapped in a guard wherever they appear in a driver.
#: `_sar_legacy_thesis()` was NOT in this list at c640ef1, which is exactly how step4's write into
#: the read-only legacy tree escaped every check (T2-review F3).
RESOLVER_CALLS = ("_sar_derived_root()", "_sar_snapshot_root()", "_sar_ssd_root()",
                  "_sar_legacy_thesis()")


def _statement_spans(lines: list[str]) -> list[int]:
    """`index -> id of the bracket-balanced statement each line belongs to`.

    A line continues the statement above it while a bracket is open, or after an explicit backslash
    continuation. Quotes are tracked only well enough to keep a bracket inside a string literal from
    opening a statement — this decides nothing on its own, it only decides which lines may excuse
    each other, and getting it wrong in the safe direction means MORE lines are flagged, not fewer.
    """
    spans, depth, current, cont = [], 0, 0, False
    for line in lines:
        if depth > 0 or cont:
            spans.append(current)
        else:
            current += 1
            spans.append(current)
        code, quote, i = [], None, 0
        while i < len(line):
            ch = line[i]
            if quote is not None:
                if ch == "\\":
                    i += 2
                    continue
                if line.startswith(quote, i):
                    i += len(quote)
                    quote = None
                    continue
                i += 1
                continue
            if ch in ("'", '"'):
                quote = line[i:i + 3] if line[i:i + 3] in ('"""', "'''") else ch
                i += len(quote)
                continue
            if ch == "#":
                break
            code.append(ch)
            i += 1
        depth += sum(c in "([{" for c in code) - sum(c in ")]}" for c in code)
        depth = max(depth, 0)
        cont = line.rstrip().endswith("\\")
    return spans


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _walk(root: pathlib.Path) -> list[pathlib.Path]:
    if root.is_file():
        return [root]
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if SKIP_DIRS & set(p.parts) or p.name in SKIP_FILES:
            continue
        out.append(p)
    return sorted(out)




def test_t8_statement_spans_group_a_multi_line_expression_and_nothing_else():
    """The excusal's only moving part, pinned on its own so the rule above cannot be widened by a
    quiet change here. Brackets group; a bracket inside a string does not; a comment does not; a
    backslash continuation does."""
    lines = ['a = 1',
             'b = f(',
             '    2,',
             ')',
             'c = "a ( b"',
             'd = 3  # ) not a bracket',
             'e = 4 + \\',
             '    5',
             'f = 6']
    spans = _statement_spans(lines)
    groups = [[i for i, s in enumerate(spans) if s == g] for g in sorted(set(spans))]
    assert groups == [[0], [1, 2, 3], [4], [5], [6, 7], [8]], groups


# --- residual R1: the ADDED list is no longer pure trust -----------------------------------------
def test_added_files_are_content_pinned():
    """Lock (a). An ADDED file's bytes are declared; changing them without editing the declaration
    fails. Without this, `ADDED` grants a file permanent freedom to become anything later."""
    for rel, (want, why) in sorted(ADDED.items()):
        f = REPO / rel
        assert f.is_file(), f"{rel} is declared ADDED but is not in the tree"
        assert why.strip(), f"{rel}: an ADDED entry must carry a reason"
        got = _sha(f.read_bytes())
        assert got == want, (
            f"{rel}: content changed since it was declared ADDED.\n"
            f"  declared sha256 {want}\n  actual   sha256 {got}\n"
            f"If the change is intended, update the pin AND say why in the commit.")


def _is_auto_executed(rel: str) -> bool:
    name = pathlib.PurePosixPath(rel).name
    return name in AUTO_EXECUTED_BASENAMES or name.endswith(AUTO_EXECUTED_SUFFIXES)


def test_no_auto_executed_file_is_added_without_a_declared_exemption():
    """Lock (b), the one the reviewer's attack needs. Python runs `conftest.py`, `__init__.py`,
    `sitecustomize.py` and `*.pth` with nobody importing them by name, so an entry of that shape in
    ADDED is a silent code-injection slot: the reviewer demonstrated a `pipeline/units/
    u0_foundation/conftest.py` whose `pytest_configure` rewrote a signed redline threshold, with all
    tests green. Such a file now needs a SECOND, separate declaration - and the exemption is
    announced on every run, so it cannot be quiet."""
    offenders = [rel for rel in sorted(ADDED) if _is_auto_executed(rel)
                 and rel not in AUTO_EXECUTED_EXEMPTIONS]
    assert offenders == [], (
        "auto-executed file(s) declared ADDED with no entry in AUTO_EXECUTED_EXEMPTIONS: "
        f"{offenders}. Python executes these without an explicit import, so adding one is a code "
        "path nobody reads. Declare it in AUTO_EXECUTED_EXEMPTIONS with a justification, or - "
        "better - do not add it.")
    assert len(AUTO_EXECUTED_EXEMPTIONS) == N_AUTO_EXECUTED_EXEMPTIONS, (
        f"{len(AUTO_EXECUTED_EXEMPTIONS)} exemption(s), ledger declares "
        f"{N_AUTO_EXECUTED_EXEMPTIONS}. Bump the count deliberately, in the same commit.")
    for rel, why in sorted(AUTO_EXECUTED_EXEMPTIONS.items()):
        assert rel in ADDED, f"{rel} is exempted but not ADDED - stale exemption"
        assert len(why.strip()) > 40, f"{rel}: an exemption needs a real justification"
        body = (REPO / rel).read_text(encoding="utf-8")
        bad = [tok for tok in FORBIDDEN_IN_EXEMPTED if tok in body]
        assert bad == [], (
            f"{rel}: an exempted auto-executed file may not define {bad} - that is the exact shape "
            f"of the demonstrated redline-rewrite attack.")
        msg = f"AUTO-EXECUTED FILE EXEMPTION IN FORCE: {rel} - {why}"
        print("\n*** " + msg)
        warnings.warn(msg, stacklevel=1)


def test_no_auto_executed_file_is_added_or_present_without_a_counterpart():
    """Kept from T2 with nothing left to except: ADDED is empty, so the exemption table is empty and
    its count is 0. A future auto-executed addition still needs two declarations plus a count bump,
    and the partition test above rejects it outright until then."""
    assert AUTO_EXECUTED_EXEMPTIONS == {} and N_AUTO_EXECUTED_EXEMPTIONS == 0, (
        "an auto-executed exemption reappeared. T2-review F1 showed content pinning cannot defend a "
        "file that is already exempted: the payload edit and the re-pin are the same edit. Put the "
        "sys.path work in pytest.ini instead.")
    offenders = [rel for rel in sorted(ADDED) if _is_auto_executed(rel)
                 and rel not in AUTO_EXECUTED_EXEMPTIONS]
    assert offenders == [], (
        "auto-executed file(s) declared ADDED with no exemption: "
        f"{offenders}. Python executes these without an explicit import.")
    for rel, why in sorted(AUTO_EXECUTED_EXEMPTIONS.items()):
        msg = f"AUTO-EXECUTED FILE EXEMPTION IN FORCE: {rel} - {why}"
        print("\n*** " + msg)
        warnings.warn(msg, stacklevel=1)


def test_the_test_path_bridge_lives_in_pytest_ini_not_in_the_port():
    """The F1 fix, asserted rather than assumed: the nine ported `*/tests` directories reach
    sys.path from pytest.ini, u6_assemble first (it is the only unit doing a bare
    `import conftest`), and no conftest.py was left behind inside `pipeline/`."""
    ini = (REPO / "pytest.ini").read_text(encoding="utf-8")
    listed = [ln.strip() for ln in ini.split("pythonpath =", 1)[1].splitlines() if ln.strip()]
    on_disk = sorted(p.relative_to(REPO).as_posix() for p in (REPO / "pipeline/units").glob("*/tests"))
    assert sorted(listed) == on_disk, {"pytest.ini": sorted(listed), "on disk": on_disk}
    assert listed[0].endswith("u6_assemble/tests"), listed[0]
    bare = sorted(
        d.parent.name for d in (REPO / "pipeline/units").glob("*/tests")
        if any(re.search(r"^\s*(from conftest import|import conftest)\b", f.read_text("utf-8", "ignore"), re.M)
               for f in d.glob("test_*.py")))
    assert bare == ["u6_assemble"], (
        f"bare `import conftest` is resolved by sys.path order, so exactly one unit may use it; "
        f"found {bare}. Reorder pythonpath in pytest.ini, or make the new call site unambiguous.")
    assert not (REPO / "pipeline/units/conftest.py").exists(), (
        "the auto-executed test-path bridge is back inside the port (T2-review F1)")


# --- residual R3: the read/write guards are wired into the drivers, not merely available ---------
def test_the_guards_have_at_least_one_caller_outside_their_own_tests():
    """The literal residual: `grep -rn require_readable\\|require_writable pipeline` used to hit
    only the definition. Now it must hit a driver too."""
    callers = [f.relative_to(REPO).as_posix() for f in _walk(REPO / "pipeline")
               if f.suffix == ".py" and f.name != "paths.py"
               and any(g in f.read_text(encoding="utf-8", errors="ignore") for g in GUARD_CALLS)]
    assert callers, "no ported driver calls the path guards - residual R3 is not closed"


# --- T2-review F2: every file under pipeline/ must be accounted for -------------------------------
# `PORTED` maps ROOTS, and `pipeline/drivers/u3_run` is mapped as a single FILE, so `_walk` never
# enumerated that directory: a stdlib-shadowing `pipeline/drivers/u3_run/json.py` was invisible to
# every test while sitting on `sys.path[0]` for the invocation the drivers README documents. The
# whole-tree scan below closes it by partitioning the layer: every tracked file under `pipeline/` is
# PORTED (has a legacy counterpart), ADDED (sha-pinned), or REPO_AUTHORED (declared here). Anything
# else fails, whatever its name.
# repo-relative path -> (sha256 of the file, why it exists)
#
# T2 re-review R2: this used to be a plain path -> reason dict with none of the three protections
# `ADDED` was given. One declared line - `"pipeline/drivers/u3_run/json.py": "small helper"` - put the
# F2 stdlib shadow straight back on `sys.path[0]` for the documented U3 invocation, with 47 guard
# tests and 107 root tests green. The partition is only as strong as the escape hatch, so the hatch
# now carries the same four locks: a sha256 pin, a pinned count, the auto-executed-basename ban, and
# - new, because this is where code lives - a stdlib-shadow ban plus a rule that a `.py` may only sit
# DIRECTLY in a declared code directory.
REPO_AUTHORED: dict[str, tuple[str, str]] = {
    "pipeline/README.md": (
        "0c5753c1200017a3caf4e60938d3908d893f012715dc58d9cd6a40c89d5cb952",
        "layer documentation written for this repo",
    ),
    "pipeline/drivers/README.md": (
        "e334d85aa8f8a2d74742b0f0165ebf5e5091c9c56dc7ba3c07aeb27ff9976bc1",
        "driver provenance, the gap register and the per-driver overwrite table",
    ),
    "pipeline/lib/paths.py": (
        "4418aaa522acc4204aef363ade284fd76b0c3b25acf0d2e66aaa82b56d4a2009",
        "path resolution and the write barrier - the only thing the port is allowed to call",
    ),
    "pipeline/frames/make_slim.py": (
        "c812610ede59bd2933f41d09c99ddf1a917570c71b510eec61441ffa40ebab12",
        "M1: one implementation replacing six legacy copies of the P3 slim builder; equality to the "
        "frozen slims is enforced by tests/test_make_slim.py (T2-review N2)",
    ),
    "pipeline/fwci/README.md": (
        "8aabaf6f15a7f30f50951f6b2a9cc5c3cd857aadff46fd56ded94c8b86cd99e6",
        "FWCI provenance: which script produced which surviving artifact, the caliber the expected "
        "table encodes, and the cost of the stage that stays switched off",
    ),
    "pipeline/fwci/run_fwci.py": (
        "e92cfe0b403ec0059c6afb229a4d9d102a9ada46b58bfa2592061af5c27afe9e",
        "the FWCI launcher: both ported scripts write to a directory derived from their own "
        "__file__, a line carrying no absolute path and therefore untouchable, so the run directory "
        "is staged through output_target() from outside - and the 36-minute scan is gated here",
    ),
    "pipeline/NOT_REPRODUCIBLE.md": (
        "0492d246b515f4b4032bb0c2b660781bec7b7feb4ddb5bb775815712f3c64b0a",  # R1 release repin: private-record markers and the final canon/custody boundaries.
        "the D2 register: legacy code and artifacts that cannot be re-executed, and what a "
        "replicator can check instead. Started in T4, finalized in T8",
    ),
    "pipeline/rosters/README.md": (
        "a6c3fc2bc9c670412857972adb4fd6667d1d6cd9130c5503053ca4fbd327e790",
        "roster provenance: which of the two merge scripts produced the frozen parquet and how that "
        "was settled by re-execution rather than by mtime, the gold chain, and the two gaps",
    ),
    "pipeline/rosters/run_rosters.py": (
        "c157ee1228724c55bf6ccd6e55e92158ae7ed86235e00d06d6a8eeafb45eb720",
        "the roster launcher: every roster script's one absolute constant is BOTH its input root and "
        "its output root, so this builds a staging mirror with the inputs symlinked in and points "
        "the constant at it through staged_run_dir() - the only mechanism under which those scripts "
        "can run at all without rewriting the legacy human-verification evidence",
    ),
    "pipeline/stars/README.md": (
        "4b33f0828d2cdb7a11540d0d638782a39e45125794254ff270bc076e915fa98a",
        "the star layer's documentation: the four signed gates verified line by line against the "
        "code that runs, the 00_make_u4_aug.py provenance ruling with its evidence, the "
        "rerun comparison table, and three places where the legacy code disagrees with itself - "
        "reported, never repaired",
    ),
    "pipeline/stars/run_stars.py": (
        "2b82cff5da31296ec2872af426c3da2f31e3ddd7d14185b4cd07ecda53eb35be",
        "the stars launcher: it stages a run directory, links the stage's inputs in, and - for the "
        "two stages that need the ranking machine - pre-imports THIS repo's run_screening and "
        "screening_lib so the ported scripts' `sys.path.insert` into the legacy tree cannot supply "
        "them. It also carries the cost gates for the two expensive stages and the two live-API "
        "ones",
    ),
    "pipeline/frames/run_frames.py": (
        "3625b39fdeac1af688d79c8432e7f0cc10847cf0f5477f033e7d61cdbdf7a04e",
        "the frames launcher: every frame builder derives its run directory from its own __file__ "
        "or writes to a fully-expanded legacy destination, so this stages a run directory under "
        "output/, links the stage's inputs in, hands the ported constants the mirror through "
        "$SAR_STAGE_ROOT, and pre-imports this repo's U0/U4 modules so the builders' sys.path.insert "
        "into the legacy units tree cannot supply them",
    ),
    "pipeline/frames/README.md": (
        "065e1a70b706ffaa0d4256e0acec4f7b04e65ce11c28acb4337a7840cc579f5f",
        "the frame layer's documentation: per-builder provenance with the evidence that settled it, "
        "the acceptance table (21 frozen frames, builder, mode, verdict), the two producers "
        "recovered from the author's working records, and the D1 criterion applied per frame",
    ),
    "pipeline/drivers/run_driver.py": (
        "ffddacad872143f118e956c39591d9f2462aa101481670286641722394347afb",
        "the launcher: resolves each driver's OWN declared output constant through output_target() "
        "before runpy-ing the unmodified script. It is what makes step3 mechanically barred - its "
        "U6_OUT is built from a legacy line holding no absolute path, so the barrier cannot attach "
        "inside the port (T2 re-review R4)",
    ),
    # --- T8: the entry point, its inventory, the intermediates manifest and the AWS runbooks ---
    "pipeline/run_all.sh": (
        "524894c37132c1b7fa165d9ff9125371c91436cc451fcfec7cc0de934ae9ca22",  # R1 release repin: select the labelled October config when SAR_PATHS_CONFIG is unset; the analysis entry uses M.
        "the pipeline layer's entry point: it runs the four launchers' default stages in dependency "
        "order, gated on exit codes, then the acceptance proof. The 17h U1 fetch is not a stage here "
        "at all, the 37-minute FWCI scan needs --expensive and prints its cost first, and no AWS step "
        "is reachable under any flag",
    ),
    "pipeline/lib/stages.py": (
        "6fe3057112f8a64bb9739f7225037b2babffcba6c555473300fe74ac7a1357b6",
        "the stage inventory: run_all.sh reads each launcher's own STAGES object through this module "
        "rather than restating the list, and it declares the cost CLASS of every gated stage (ssd / "
        "long / api), which is what decides the flag that turns it on",
    ),
    "pipeline/MANIFEST_intermediates.md": (
        "f02a40fc7b89cd0ee757fd041a17fbfcd561519df215c3789e6fd5c8bcd7a71a",
        "every intermediate artifact between the snapshot and the frozen frames: producer, sha256 and "
        "availability (repo / rebuildable / legacy / SSD / gone). The answer to 'can I rebuild this?' "
        "and 'where does the chain actually break?'",
    ),
    "pipeline/aws/README.md": (
        "841e3d8322b3120b2d86d207f838261605cdabc5bf62e3e29dc6efe9607f2e86",
        "the two cloud steps: what ran, on what machine, when, for how long and for how much, and "
        "what to check instead of re-running them (tools/verify_cloud_custody.py)",
    ),
    "pipeline/aws/launch_p3_dcdh.sh": (
        "0522ac191d1b933dc0be3283309fbc7de24398abdb2d7e95dbfd797bb28df00e",
        "the r6i.16xlarge launch for the four Panel-3 dCDH cells, written down. Every aws command is "
        "inside a quoted here-document: running the script prints the runbook and exits",
    ),
    "pipeline/aws/launch_u1_fetch.sh": (
        "f9f21d3525cec0a5c55390b493539becf3c85b04cabc4493e93f83e8dcb5e77a",
        "the i4i.4xlarge launch for the 17-hour snapshot fetch, written down, with the "
        "instance-sizing rule and the three snapshot verification checks. Same shape: it prints and "
        "exits",
    ),
    # --- cal2026-08-28: the author-signed caliber layer (Task 1 of the caliber rebuild) ----------
    "pipeline/stars/caliber_2026-08-28/README.md": (
        "0be4ff0c53dd8cf5bb08635fa81b4c90366362ae7a5fc1bd6b00b8e535d23741",
        "the caliber layer's documentation: the two signed predicates, the five rulings, the "
        "restake equivalence proof and the machine outcomes, with the exact new event counts",
    ),
    "pipeline/stars/caliber_2026-08-28/caliber.py": (
        "234fdc804e70d5bbd136dd987a5bd50b5ed0863f64445c9ed7b270972842d35f",
        "the two author-signed predicates (D-A aage>=2 everywhere, D-B uniform window 1999-2024 on "
        "arrival_true) plus the OLD caliber's four window paths kept importable for the side-by-side",
    ),
    "pipeline/stars/caliber_2026-08-28/cleaned_works.py": (
        "95fc9a991ab92c303e63e5697aac1c445ab91fc8d1272f21d414bfa99f899441",
        "reader for the signed per-star cleanup DATA table data/cal2026-08-28/calls_2026-08-28.csv "
        "(exclusions, the split-ID merge list for A5017222669, first_pub anchors); aage derives from the "
        "anchors, never hand-typed",
    ),
    "pipeline/stars/caliber_2026-08-28/restake_equiv.py": (
        "76d654b522d86ef0a46a321507c3562998a250da53a356354f4024366a224042",
        "the caliber-layer equivalent of the ported 72 restake, needed because 72 cannot accept an "
        "injected first_pub; equivalence is proved by reproducing frozen restake rows byte for byte "
        "(tests/test_caliber_2026_08_28.py)",
    ),
    "pipeline/stars/caliber_2026-08-28/run_caliber.py": (
        "072c1d26fc757f15a726cf2d0038f8e247dc3026cd99207b830d90a427ea092c",
        "the caliber driver (declared in LAUNCHERS): stages and runs the ported 72 on the signed "
        "inputs the way run_stars.py would, runs the equivalence machine, derives the 71-row "
        "verdict set and the cal event tables, and STOPS on any surprise beyond the signed delta",
    ),
    "pipeline/stars/caliber_2026-08-28/supplement_fetch.py": (
        "08c98f7c67763f1432c3cb93152581246a11d4052d53015bd21a34a668ac6ffd",
        "Task 2's live-OpenAlex machinery: 70_prep's wire protocol and byte-shaped supplement row, "
        "plus a request log 70_prep never kept, the data-driven cleanup filters, and A5062352558's "
        "cache-first sourcing (the frozen 227-work cache supplies membership/year/authors; the "
        "live pass supplies only the type field and post-08-15 additions)",
    ),
    "pipeline/stars/caliber_2026-08-28/run_supplement.py": (
        "73d032db332a5c340f379f5864a45000090611c376d8e96e5e45a8d0a7fc0f0c",
        "the Task-2 driver (declared in LAUNCHERS; runs no ported script): fetches the five new "
        "stars' works + the split-ID merge works of A5017222669, applies the signed cleanups as data, "
        "assembles the cal supplement on the frozen fnfix bytes, freezes stars_excluded_cal and "
        "the Task-3 row-level expectations, and STOPS on any moved profile",
    ),
    "pipeline/stars/caliber_2026-08-28/frames_stage.py": (
        "bc3ee0d93d5aadf325f839c7ebdf2e5d8890abdc864142240147c70107285495",
        "Task 3's staging library: the shadow legacy tree ($SAR_LEGACY_THESIS) that hands the "
        "ported frame builders the cal event tables/supplement/exclusions at the exact paths they "
        "resolve, the econ single-event removal for A5044432173 (ruling R-T3-1), the sha-pinned verbatim staging of "
        "the prodlib trio, and the strict-walk / keyed row-accounting primitives",
    ),
    "pipeline/stars/caliber_2026-08-28/cal_accounting.py": (
        "d00f0d0fc5ec21aab3ac0c57754a7ecb289634aa20e095429279eafcbe6cfd51",
        "Task 3's row-level accounting: every produced frame against its frozen counterpart with "
        "every row in/out/changed attributed to a named cause (the removed event, five_member, new_event, "
        "h1_fwci_ulp, ex_star_ripple, coauthor_ripple); T2's pinned expectations evaluated "
        "verbatim and deviations recorded, never absorbed; internal consistency for the new events",
    ),
    "pipeline/stars/caliber_2026-08-28/run_cal_frames.py": (
        "b4f01f27df54548464b49beb6e2e9f812deecbe058bc323494ddff0cc3893a64",
        "the Task-3 driver (declared in LAUNCHERS): controls first (prodlib byte-equal, union "
        "builder H1-characterised), then the caliber rebuild per discipline through run_frames "
        "subprocesses over the shadow tree, the accounting, and the freeze into "
        "data/cal2026-08-28/frames/ — an accounting that does not close freezes nothing",
    ),
    "pipeline/stars/caliber_2026-08-28/run_cal_estimates.py": (
        "e85a11b8bfdafc0a82b3c77f09dfa835b3bed9ee91fded4626609b9bdba4185d",
        "the Task-4 driver (declared in LAUNCHERS; runs NO ported python — Rscript subprocesses "
        "over the VERBATIM analysis/estimation drivers): hash-verifies the cal frames against "
        "the cal MANIFEST, runs the 19 local cells sequentially (econ P1 twice — the determinism "
        "check), holds the old79 positive control to compare_json-EQUAL, freezes "
        "data/cal2026-08-28/estimates/ and generates the old-vs-new comparison table — a cell "
        "error, timeout, or control failure freezes nothing",
    ),
    "pipeline/stars/caliber_2026-08-28/run_cal_cloud.py": (
        "d5c921a69fe6b0544e98dd57899affca4ae50892758ecfba180d10837dc1e448",
        "the Task-5 driver (declared in LAUNCHERS; runs NO ported code and NO aws command — the "
        "money-spending commands are the operator's, per pipeline/aws/ discipline): before the "
        "upload it three-way sha-verifies the four cloud payloads (disk == cal MANIFEST == T4 "
        "registry) and writes the shipping bundle + cost estimate; after the fetch it verifies "
        "the custody chain end to end (pre-upload hashes == the instance's own md5sum -c OK "
        "lines, ALL_DONE marker, four zero exits, evcl point estimates == their mains) and only "
        "then freezes the results, extends the comparison doc through Task 4's own extractor, "
        "and regenerates the cal MANIFEST with a pure-addition assertion",
    ),
    "pipeline/stars/caliber_2026-08-28/run_cal_ledger.py": (
        "d0f804a1616f20c76c99a178b64852386aecd451554cd51b2066ff9fcf5b5cba",
        "the Task-6 driver (declared in LAUNCHERS): derives the caliber Panel-3 (A_far) ledger "
        "by running the UNEDITED analysis/paper/ledger_p3afar.py in-process with load_paths() "
        "pointed at the cal artifacts (inputs sha-verified against the cal MANIFEST; the "
        "legacy cross-check and the frozen no-effect simulations pointed at empty dirs so no "
        "old-caliber number can leak in; speed bracket staged header-only because its cap "
        "cells have no builder — NOT_REPRODUCIBLE entry 9), runs it twice and requires "
        "byte-equality, then freezes data/cal2026-08-28/data_numbers_cal_p3afar.json with a "
        "pure-addition MANIFEST assertion — any STOP freezes nothing",
    ),
    "analysis/robustness/predate/run_predate.R": (
        "07a8b7288e2c061a9f48eef397f42aa6b7b521dae3a705b386cbbc8a0d292fde",
        "Batch 2 (2026-08-28) date-shift anticipation test: the P2/P3 built-in placebo is a "
        "structural zero, so this re-runs each panel with D' = 1{year >= arrival-2}; three modes, "
        "each a line-for-line copy of the verbatim driver's prep (arrival reconstruction proved "
        "by stopifnot; shift=0 must be compare_json-EQUAL to the frozen golds)",
    ),
    "analysis/robustness/predate/run_all_predate.sh": (
        "4fd376fb98d75ea74d2d71eab7623aaa03459413943bc41079afee2103583604",
        "single entry point for the date-shift test: three shift-0 controls checked EQUAL against "
        "analysis/expected, then the seven local shifted cells, then the sha256 MANIFEST over "
        "data/predate_2026-08-28/",
    ),
    "analysis/robustness/predate/README.md": (
        "63384a727fd1a92c21311f7ad9b1eec11ffdf55c55b5496a7f4d316d9edffcc0",
        "why the built-in P2/P3 placebo carries no information, what the date-shift test measures, "
        "the cell table (incl. the two 512GB cloud cells NOT run, pending author approval), and "
        "the output layout under data/predate_2026-08-28/",
    ),
    "analysis/robustness/battery_2026-08-29/run_p1_variant.R": (
        "c9dd13c082e68b07d4b2c9e1ccd33c5aff55227f79cc83c3999be76f8aaa204a",
        "Panel 1 robustness battery T1-T4 (2026-08-29) on the canon frames: leave-one-event-out "
        "for the econ union placebo diagnosis, missing-output bounds under the thesis's stated "
        "fill rule (zero / person's own average — the exact sentences are quoted in the header), "
        "output in levels, and the never-exposed comparison pool; the prep is a line-for-line "
        "copy of run_p1.R with one marked insertion per variant (variant none / event NONE must "
        "be compare_json-EQUAL to the frozen gold)",
    ),
    "analysis/robustness/battery_2026-08-29/run_all_battery.sh": (
        "b38ac643cd0c6ceac4e7f54032dbff44025055415b522d2d80ceaf8c58956d85",
        "single entry point for the T1-T4 battery: two faithfulness controls checked EQUAL "
        "against analysis/expected, then the 12 variant cells, the 116 LOEO cells (parallel), "
        "the ranked LOEO summary, then the sha256 MANIFEST over data/robustness_2026-08-29/",
    ),
    "analysis/robustness/battery_2026-08-29/README.md": (
        "c7334d18d7565f64721743b01cc1bd8fa8e6c386a05ecebfadab1b87294d9167",
        "what each of the four checks answers, which thesis promises T2-T4 discharge (incl. the "
        "text-vs-computation mismatch of the old sample-mean bounds), the cell table, and the "
        "output layout under data/robustness_2026-08-29/",
    ),
    "analysis/robustness/inference/run_perm.R": (
        "2dc98b40cb1f76ce84169efcc578bd67c71d78ffd8f4ca26ca9d3b0278fe6f40",
        "T5 (2026-08-29) event-level permutation inference for the few-cluster disciplines: "
        "reassigns the observed arrival years across events at the exact interface each verbatim "
        "driver consumes them (reconstruction proved by stopifnot), re-estimates the headline "
        "cells; permutation 0 is the identity and must reproduce the frozen gold in-driver",
    ),
    "analysis/robustness/inference/run_all_perm.sh": (
        "e5cb5949f4be37e8bd034f3d7a52985ca87b85b0b33d6a72f13d13fd9a140644",
        "single entry point for the T5 permutation batch: nine identity controls checked EQUAL "
        "against analysis/expected, then B=500 seeded permutations per headline cell (chunked, "
        "parallel), the permutation p-value summary, then the sha256 MANIFEST over "
        "data/robustness_2026-08-29_b/perm/",
    ),
    "analysis/robustness/inference/README.md": (
        "bebe3cee01685a98603aee510733fae46a711d526b2a4e8f9a5cb16d4a42832b",
        "why conventional cluster-robust p-values are fragile at 38/33 events, the timing-"
        "permutation design and its interface proof, the p-value convention, and the output "
        "layout under data/robustness_2026-08-29_b/perm/",
    ),
    "analysis/robustness/sensitivity/run_all_sensitivity.sh": (
        "9163f4ec40910b38d4a5a8c216e3fc79d69976c8e5b25a2dd7f117a4e8a9f5e4",
        "single entry point for the T6 canon reruns (departure A/B, double-star drops, ± centre "
        "rosters): proven A_far event maps first, then each builder with its own faithfulness "
        "control, estimation by the verbatim drivers only, then the sha256 MANIFEST over the T6 "
        "part of data/robustness_2026-08-29_b/",
    ),
    "analysis/robustness/sensitivity/run_p3pos_sensitivity.sh": (
        "0c3e1d4b8b49f227cae9acf6fa1e71840e4babc8e91e68822a4a7e1e8ca0b00b",
        "entry point for the 2026-09-10 re-staging of the departure A/B and double-star checks on "
        "the dose>0 Panel 3 frames (--spec pos): proven pos maps first, econ cells recorded NOT RUN "
        "when the econ map cannot be proven (data disk), the cut-independent P1/P2 staged files "
        "checked byte-identical to the 2026-08-29 stage, then the MANIFEST over "
        "data/robustness_2026-09-10_p3pos/",
    ),
    "analysis/robustness/sensitivity/run_nocentre_afar_pos.sh": (
        "0049e800844e7ff558b6f46fbe239e030ab1d56f7c6d61aba50e4d4278fb69fd",
        "entry point for the 2026-09-10 +/- research-centre check on the dose>0 Panel 3 cell "
        "(chemistry / math_stats; economics has no centre variant by design): run_nocentre's "
        "control-then-incfel frame builds verbatim, build_afar_cut `pos` with SOURCES re-pointed "
        "by its explicit sources= parameter, the with-centre control proven content-equal to the "
        "frozen pos frames and compare_json-EQUAL to the golds before any variant cell runs, then "
        "the MANIFEST rewritten over the whole of data/robustness_2026-09-10_p3pos/",
    ),
    "analysis/robustness/sensitivity/README.md": (
        "9584edaff3263a80f6700c7842b697901c6ddaec9ab4531c7ec60c8b945a91c9",
        "the three pruned sensitivity checks re-run old-design-on-canon: which old record each "
        "follows, what had to be read from §3 itself (double-star window; disclosed), the "
        "departure-ledger coverage gap over the 37 fnfix events, and every check's own control",
    ),
    "analysis/robustness/figure4/run_save_sample.R": (
        "c09c0a00983a2d42dae8c25baa6b5a068dae179a950de21ce9cfcc5f6d50c599",
        "R1 N5 Figure 4 driver: label-prefix dispatch over line-for-line copies of run_p1.R / "
        "run_p2.R / run_p3_tp.R whose only change is save_sample=TRUE in each did_multiplegt_dyn "
        "call (text test tests/test_r1_fig4.py); writes the verbatim JSON plus "
        "<label>_sample.csv.gz and <label>_switchers.csv",
    ),
    "analysis/robustness/figure4/README.md": (
        "e74a49004deb10c7e6e1519cacc5b14a5e0adeb3dc6ae65206c5d7af1b2122c6",
        "R1 N5 documentation of the Figure 4 save_sample driver, the counting rule and the two "
        "neutrality proofs (toy panel, J1b fig4_m vs J1a main JSONs)",
    ),
    "pipeline/aws/cal2026-10/README.md": (
        "ea084d3516cbbe25994f2311d4fb516e11f1c9227ccffd4606f86eba4e89c82a",
        "the October cloud batch's directory note: which file spends money (run_cloud.sh only), "
        "what the batch is, how to run it, the five controls tests/test_aws_cal2026_10.py "
        "holds, and the second (T5 P1/P2 permutation) batch prep_t5_batch.sh assembles",
    ),
    "pipeline/aws/cal2026-10/bootstrap.sh": (
        "d2450bd072de321faf13893dd90eaf7d5b4d7a540fe08a1f89033e8e1f8b0394",
        "the instance environment recipe for the October batch: the 2026-08-28 bootstrap verbatim "
        "(r2u binaries, rustup source build of R polars, versions.txt, memory sentinel) plus "
        "r-cran-fixest for run_null.R, every log under ~/work so one tar fetches everything",
    ),
    "pipeline/aws/cal2026-10/cloudkit.py": (
        "b7012474fea6f64cb0e6769d5bbbe60f339a2e7f0e3385909f28837d8a3afc79",
        "the local half of the October cloud batch (no aws, no R, no ported code): prep assembles "
        "the payload + payload.md5 + the serial/parallel job lists + the preflight record and "
        "cost estimate (CONTROLS: the 08-28 payload.md5 and driver commands, the 08-30 shipped "
        "hashes and unit grammar are reproduced), check-md5 is the instance's own step, record "
        "writes launch_record.json and the cost line, custody writes custody_cal2026-10.json and "
        "exits 1 on any broken link; 2026-09-23: --extra-parallel 'NAME|OUTDIR|COMMAND' (the "
        "--extra-serial grammar, appended to jobs_parallel.txt) and an explicit --groups '' = no "
        "group, for the T5 batch (tests/test_aws_cal2026_10_t5.py)",
    ),
    "pipeline/aws/cal2026-10/driver.sh": (
        "ce1a06121507eccb0da0aea034f813fafe3f09844f44ce10564e0dae803ee7c7",
        "the instance-side driver template: md5sum -c payload.md5 first, the serial cells one at "
        "a time under /usr/bin/time -v, the thread-capped parallel units, one rc= line per unit "
        "in progress.log and ALL_DONE only when every unit exited 0 (the 08-30 unconditional- "
        "marker defect, maps.json check:aws #5)",
    ),
    "pipeline/aws/cal2026-10/run_cloud.sh": (
        "557230cb5d4b640a8fa8bea0daa04aa407b318f5681df1ac2b9fe1e0ca1e0077",
        "the ONLY file in the repository that can rent the machine: one r6i.16xlarge in us-east-1 "
        "with the ten-hour user-data fuse, ssh wait, detached bootstrap, payload md5 verified ON "
        "the instance before the driver starts, poll, fetch whatever happened, terminate, record; "
        "every aws call goes through aws_cli() which prints under --dry-run; resumable state "
        "markers and an EXIT trap that salvages and terminates",
    ),
    "pipeline/aws/cal2026-10/prep_t5_batch.sh": (
        "bcc2bce5a0739dc7c78bd64ff880def25049aa410096e5b070a72863e8771d14",
        "the SECOND October batch (2026-09-23): T5 timing-permutation inference for Panels 1 and 2 "
        "assembled as parallel units — the six p1/p2 rows of run_all_perm.sh's CELLS table, B and "
        "CHUNK read from that file, seed from config/seeds.yaml (asserted == the battery's SEED), "
        "identity control 0 0 per cell then chunks of 50 to 500, frames from data/frames and refs "
        "from analysis/expected; cloudkit.py prep --groups '' --extra-parallel, then run_cloud.sh "
        "--dry-run; never launches (tests/test_aws_cal2026_10_t5.py)",
    ),
    # --- cal2026-10: the October caliber (author decisions of 2026-09-22; registered here on
    # 2026-09-23) — repo-authored, beside the ported run directories and never inside one. The
    # star layer, the roster step, the network-frame rung (Piece A), the two economics chains
    # (econ_gold = Piece B, STOPPED at its control; econ920 = the canonical chain that produced
    # data/cal2026-10/frames_econ/), the Panel 3 sweep and the promotion. Pins by tools/repin.sh.
    "pipeline/stars/caliber_2026-10/README.md": (
        "9985fb4d8ed1492fb049cf27af61268c2d9004a8f5cea0b254aa9b13e1e5ccf6",
        "the October star layer's documentation: author decisions D5 / D7, the per-file table and "
        "the 2026-09-22 finding that economics was ranked on the 11-school extraction (two "
        "extractions, one machine) with its consequences for the run-2 event tables",
    ),
    "pipeline/stars/caliber_2026-10/build_calls.py": (
        "83f8d9cb7d864175c97884fc77b5e0f932a54d8a314d43bf3a3454d84c0033da",
        "assembles the per-star work-level cleanup DATA table data/cal2026-10/calls_2026-10.csv "
        "(the signed 08-28 rows carried forward + the 2026-09-22 recheck's is_mine=false calls "
        "as exclude, split ids as merge_from) and the star-id correction table; every row cites "
        "its source file, nothing hand-typed",
    ),
    "pipeline/stars/caliber_2026-10/run_caliber.py": (
        "d903036698e7d2aafc663d62791cd477a927b79030ecf7b852d6bcce9c30de21",
        "the October re-rank driver (declared in LAUNCHERS): every event star of the 08-28 caliber "
        "through the multidisc ranking machine (restake_equiv) with all per-paper cleanups, "
        "controls E1 (the 71 candidates byte-identical to restake_2026-08-28.csv) and E2 (the 42 "
        "chem/math stars at their 08-13 percentiles), the signed predicates and the top-5% flag",
    ),
    "pipeline/stars/caliber_2026-10/restake_econ11.py": (
        "e9388d21e0d1d64f95b90e0f8488abecfdfd13a69e0e866f5eca46b25f0a7d66",
        "the economics re-rank on the 11-school extraction the July machine ranked on (declared "
        "in LAUNCHERS): the SAME _POOL_SQL machine on u1_full_11school_2026-07-16, with the 35 "
        "July machine percentiles as its control (4 dp) before the 17 rechecked stars are ranked",
    ),
    "pipeline/stars/caliber_2026-10/run_cal_estimates.py": (
        "fc8cdcf7a7cc5799311a745dc4ce58f64902e1846a0c15f55ca18dacb77113c0",
        "the October local-estimation driver (declared in LAUNCHERS; runs NO ported python — the "
        "VERBATIM R drivers through their own argv + $SAR_OUT contract, and the pos/med cut "
        "builder with explicit sources): frames hashed, the 08-28 positive control under "
        "--control, the 28 cells, the old-vs-new comparison; a failed control freezes nothing",
    ),
    "pipeline/stars/caliber_2026-10/write_events.py": (
        "0a7bc3cd7e29267c8488fd173992ba10e8c65348fc88f3a53b25ce71f1cca836",
        "writes the October event tables data/cal2026-10/events_<field>_cal2026-10.csv (+ the p05 "
        "subsets, events_decision_2026-10.json and MANIFEST) from the per-machine verdicts: the "
        "08-28 economics table minus the events whose cleaned stock fails the cut on the "
        "extraction that admitted them, the run-2 chem/math verdicts less the 08-13 keep ruling",
    ),
    "pipeline/rosters/cal2026-10/merge_network102.py": (
        "07e4b51e2af23b9d2bde81d73c4548438570460e3d0e1d0a80cbd76919c7a780",
        "the D3 roster step: folds the 2026-09-13 two-round verification of the 102 never-verified "
        "network-route economists into the verified economics roster under the author's five "
        "rulings of 2026-09-22, which are DATA in data/cal2026-10/roster_overrides_2026-10.csv",
    ),
    "pipeline/frames/cal2026-10/README.md": (
        "7d65355acea65ae3ea3afbfd4d6d15d83bb1c6e95402e9a60108db6d3161c6db",
        "Piece A's documentation: the authority (the author's decisions D1-D5, private archive), the per-file table, how "
        "to run the controls, and the 2026-09-22 adversarial review findings (the person-level "
        "outcome exclusion, control C1e)",
    ),
    "pipeline/frames/cal2026-10/configs/chemistry.json": (
        "9118ee46c5a2735b337d5b07e1b81beaa5d26abc6ef87934810fc068ad9d5099",
        "the chemistry prodlib config: the frozen fnfix config (= the 08-28 cal config) with path "
        "placeholders (${DERIVED}, ${LEGACY_V2}, ${SHADOW}, ${RUN_DIR}) that stage.render_config "
        "fills",
    ),
    "pipeline/frames/cal2026-10/configs/math_stats.json": (
        "bfee4d9a3cce938ad1b307b163b89ea001c3fa932108dd64a27543ba59075895",
        "the math_stats prodlib config: the frozen fnfix config (= the 08-28 cal config) with the "
        "same path placeholders that stage.render_config fills",
    ),
    "pipeline/frames/cal2026-10/configs/econ.json": (
        "2ac2df5d70895dad89c29a5de3b5a58214d28fe2d2827af830c371d620eb2119",
        "the NEW economics prodlib config: all events in one run, u4_frozen events from a derived "
        "u4_aug pair, the network pool = the verified October roster through the U2 person map "
        "(D2/D4), the star-edge supplements; every departure from econ_fnfix.json is recorded "
        "in its _cal2026_10_note keys",
    ),
    "pipeline/frames/cal2026-10/stage.py": (
        "63adaba5fd0c939fa5a768065530f0d4ba02194d916d600c725e13551b79ecaf",
        "Piece A's staging library: the shadow input tree (frozen links + the October tables + "
        "their derived companions + the econ derived inputs, every entry recorded with its "
        "sha256), config rendering from configs/<field>.json, the pinned prodlib run in process; "
        "reuses caliber_2026-08-28/frames_stage.py by import, never run as a script",
    ),
    "pipeline/frames/cal2026-10/inpost_filter.py": (
        "e4ac5bad3d5c3b40b613435f7f4191163408eba4f544d17100b06dd0c9e353f9",
        "the D2 in-post stage: drops every network-route row of a prodlib output frame whose "
        "incumbent held no roster spell at a sample department of the field in the arrival "
        "year (the 2026-09-13 diagnostic's join promoted to a construction stage by the author's "
        "ruling of 2026-09-22); byte-preserving, with a per-event / per-class build_report",
    ),
    "pipeline/frames/cal2026-10/fetch_star_id_supplement.py": (
        "cfc2a2fc39818b989427213ee095209872a7cf29412f51fcd60e34e155b7bef2",
        "Piece A's one live-API step: the star-works supplement for every star id the October "
        "caliber corrects (D5: A5091326353), on the 08-28 supplement_fetch wire protocol and 70_prep "
        "row shape, behind its own --execute gate, with the 09-22 works cache as a tripwire",
    ),
    "pipeline/frames/cal2026-10/run_controls.py": (
        "fd5de775c65458c159559991d0e4276b1fac83c87d993113b82c638bc97ab914",
        "Piece A's controls C1 / C1e / C2 / C3 (+ --econ-smoke): the new staging, configs and "
        "in-post stage must reproduce the frozen 2026-08-28 objects on the OLD inputs before "
        "anything runs on the October inputs; runs one verbatim-staged legacy script (prodlib "
        "build_frame.py, sha-pinned) inside a staged_run mark and freezes nothing",
    ),
    "pipeline/frames/cal2026-10/run_cal_frames_chemmath.py": (
        "3cc2a6e16d1c19e4bd41be1f01c61eceec069f5cbde61f48907441782fd44a06",
        "the October chemistry / math_stats frames driver (declared in LAUNCHERS): the control "
        "chain that must reproduce the 08-28 frozen products (prodlib BYTE_EQUAL, the gold "
        "builders through run_frames.py subprocesses, the R cells compare_json-EQUAL), then the "
        "October chain with the D2 in-post stage, a row-level accounting with named causes only, "
        "and the freeze into data/cal2026-10/frames_<field>/",
    ),
    "pipeline/frames/cal2026-10/run_cal_afar.py": (
        "b8c825de9536092b9316e847583ad09694cc68232c8644fcb61fecc21618d1ac",
        "the October Panel 3 sweep (declared in LAUNCHERS): the verbatim afar stage through a "
        "run_frames.py subprocess over the October pair tables, exactly as the 08-28 driver's "
        "phase A ran it, then the pos / med cuts and the counts-by-spec table the paper ledger "
        "reads (its rate definitions recovered by matching the frozen table on all six rows)",
    ),
    "pipeline/frames/cal2026-10/assemble_frames.py": (
        "96c9e4bd011b9384957ce86cf364eedb1d51086f65bce47e78370c22540bf0e9",
        "gathers the October caliber's per-piece freeze directories into data/cal2026-10/frames/ "
        "under the canonical data/frames basenames (what analysis/run_all.sh, the batteries and "
        "the cloud launcher read), with a MANIFEST; a copy step that builds nothing",
    ),
    "pipeline/frames/cal2026-10/promote.py": (
        "5310d762b15a36249aecf66b3e0763963bf516478977518af3c13d43ffc652dd",
        "the promotion step: data/frames <- data/cal2026-10/frames, analysis/expected <- the 25 "
        "local golds (the four cloud cells pending their custody chain), freeze_expected's "
        "EXPECTED list, both MANIFESTs, and every replaced gold's old/new sha256 into "
        "data/cal2026-10/expected_refreeze_2026-10.json — the a22a27e recipe done again",
    ),
    "pipeline/frames/cal2026-10/econ_gold/README.md": (
        "8b61f3712d9ed3f7dafbc2220605ed178e2cfa1ad7eac03099e303868168831f",
        "Piece B's documentation: the per-file table and the review verdict — CONTROL NOT_EQUAL, "
        "STOPPED (economics through the gold chain re-defines y / dose / age_gap), --cal "
        "unimplemented, and the decision the author has to make before anything downstream runs",
    ),
    "pipeline/frames/cal2026-10/econ_gold/DIFF.md": (
        "a865f256001559fd18e40823c65e6faf20e8833cbd4d09fbad8bd2ab740e819d",
        "the three clone diffs against the pinned gold builders (generated 2026-09-22 by "
        "difflib.unified_diff, the originals' sha256 from tests/pipeline_ported.sha256 asserted at "
        "generation): the header block and the field / path wiring only, no computation line",
    ),
    "pipeline/frames/cal2026-10/econ_gold/10_build_union_frame_gold_econ.py": (
        "be826b87d6ee0afacef015e4cf1f4a1e0f049b48e0a24e3dfba8ca05a68f0afd",
        "Piece B clone of the pinned union-frame gold builder admitting --field econ (U2 person "
        "map, econ's own signed-star table); staged and run by run_econ_gold.py against a shadow "
        "legacy tree; the wiring hunks are listed in econ_gold/DIFF.md and asserted by "
        "tests/test_cal2026_10_piece_b.py",
    ),
    "pipeline/frames/cal2026-10/econ_gold/20_rebuild_y_gold_econ.py": (
        "0e0fd0baa7b7e8220ffa397ba0893d5e37f77133e8d3ca6afdd1bdf5ae76498a",
        "Piece B clone of the pinned y-rebuild admitting --field econ (U2 person map, econ's own "
        "signed-star table); staged and run by run_econ_gold.py against a shadow legacy tree; "
        "wiring hunks in econ_gold/DIFF.md, asserted by tests/test_cal2026_10_piece_b.py",
    ),
    "pipeline/frames/cal2026-10/econ_gold/30_build_panels23_gold_econ.py": (
        "7a27de6ec5f42654b8756b4c67c40749b057cadf056befa4aa819769e1dcdcd3",
        "Piece B clone of the pinned panels-2/3 gold builder admitting --field econ (U2 person "
        "map); staged and run by run_econ_gold.py against a shadow legacy tree; wiring hunks in "
        "econ_gold/DIFF.md, asserted by tests/test_cal2026_10_piece_b.py",
    ),
    "pipeline/frames/cal2026-10/econ_gold/econ_gold_stage.py": (
        "3ef6b920bde85641fd6175e08994d759b6cb7611728434e8aeac24e94687ad75",
        "Piece B's library: the id-shape adapters between the economics and the gold conventions "
        "(P_ prefix, star:year <-> star:school), the D4 pool filter, the shadow staging names and "
        "the row-level accounting; imported by run_econ_gold.py, never run as a script",
    ),
    "pipeline/frames/cal2026-10/econ_gold/run_econ_gold.py": (
        "a6ddb44db4af68e97a4e90273bc46b19f6d2321f8821b03654cb414e1403faa2",
        "Piece B's launcher (declared in LAUNCHERS): R0 estimator control -> shadow -> the three "
        "clones in subprocesses -> restored shapes -> R cells -> compare_json -> accounting; its "
        "docstring is the assumption ledger A1-A7 and carries the control result (NOT_EQUAL — "
        "stopped; --cal unimplemented)",
    ),
    "pipeline/frames/cal2026-10/econ920/DIFF.md": (
        "720c3617b9cdc7690e03363a6fca5a195dca175a2d3c8f83f18ac6e0f8e49ceb",
        "the econ920 union-rung clone's diff against its pinned legacy original (generated by "
        "make_clone.py, never edited by hand): 17 lines removed / 37 added — 14 hunks each one "
        "absolute-path constant or output path replaced by a config lookup, 3 lines re-emitted "
        "with the public copy's comment wording; the original's machine paths are shown as "
        "placeholders",
    ),
    "pipeline/frames/cal2026-10/econ920/make_clone.py": (
        "daf3d56355dc91138007bcd690fb4cb1ffade2ea9efd052b983503cab2e24d3b",
        "the generator of the econ920 clone and of its DIFF.md: textual substitution of the legacy "
        "absolute-path constants (held here as the strings to replace, with asserted hit counts) "
        "by config lookups, after the public copy's comment-wording rule (WORDING_RX); --check "
        "asserts the tracked clone is current. Not a builder",
    ),
    "pipeline/frames/cal2026-10/econ920/00_build_frame_econ920_cal.py": (
        "cc68f230512f25adf92523966475d3ff319ccd39e1a8df98cb83f00e3fd7032a",
        "the path-wired clone of the un-ported legacy union rung econ_fnfix_2026-08-15/code/"
        "00_build_frame_econ920.py (sha-pinned in DIFF.md): inputs and outputs from a JSON config, "
        "every computation line kept; run in process by run_econ920.py inside a staged_run mark",
    ),
    "pipeline/frames/cal2026-10/econ920/econ920_lib.py": (
        "b1aa9a9dda1cc747f4547655822642fcf7803d30a7452150c84f579ba0cd823c",
        "the econ920 library: the D1-D5 network-frame filters, the shadow legacy tree, the clone "
        "runner and the row-level proofs; imported by run_econ920.py, never run as a script",
    ),
    "pipeline/frames/cal2026-10/econ920/fetch_patch_supplement.py": (
        "dbe0ea68614553b15a6708259ad0aae7641c8cb7403a49ba1b3ea3658d29b9d4",
        "the OpenAlex works-by-author fetch (network, behind its own --execute gate) for the "
        "October roster additions the ported 04_rebuild_y.py has no aggregate for; products "
        "frozen in data/cal2026-10/patch_supplement_2026-10/ and read by the union clone through "
        "the shadow (frozen patch + supplement)",
    ),
    "pipeline/frames/cal2026-10/econ920/run_econ920.py": (
        "96a63a5a791c7247ea9d804184560b167b39fc6063cc56dc377768eedb51cccd",
        "the econ920 launcher (declared in LAUNCHERS): four controls (the clone byte-equal on the "
        "frozen inputs; the re-run == the 08-28 surgery; the chain == data/frames + the four golds; "
        "filter (a) == the 2026-09-13 verified-pool cells) and a failed control stops it, then the "
        "October run into data/cal2026-10/frames_econ/ (report build_report_econ920_2026-10.json)",
    ),
    "pipeline/aws/r1/README.md": (
        "0f6419c171600093ba0c6319e7fd0ce07ff7e1163b7b9a3a07cece5c35399013",  # R1 release repin: measured spend totals and the public-e2e runtime/memory measurement contract.
        "the AWS kit's page: what ran on AWS, where its records are, how the runs were controlled, the files",
    ),
    "pipeline/aws/r1/r1kit.py": (
        "410e3aa3b733d589858843520971879ff3f0e01fa89cc30b1900c2013dd49bc9",
        "the R1 Mac-side launcher: payload from a commit, boot script, one instance, watch, result, cost ledger",
    ),
    "pipeline/aws/r1/userdata.sh.tmpl": (
        "90b5a4f612e47746d39ceb342042529d66347ca31892c5d36775cad5c5bf2874",
        "the R1 instance boot template: hard fuse first, deadline unit, sha checks, steps as ubuntu, push, power off",
    ),
    "pipeline/aws/r1/run_tests_r1.py": (
        "145db076322457def9ce63b90aaf1c2bf410b285616adc2b9ed234cbf626ecd3",
        "the R1 instance-side test runner: red/green/noregress expectations judged per commit",
    ),
    "pipeline/aws/r1/recover_rk.py": (
        "ce637e7e3585de9035be10c13b3aa0a936cfea3247ae7900866e5389caa0ce53",
        "the R1 recovery job: RK1-RK5 from S3, sha and control gates, kit copies equal their rebuilds from the recorded command history, launch-side files rebuilt",
    ),
    "pipeline/aws/r1/rk6_requests.py": (
        "03e59ed108ff5e9c9a09ae0b577350e237c3724de4bd4312b6933bbbe3ccfac5",
        "the R1 RK6 inputs: requests from the merged table, recovered RK1 production inputs, the RK6a summary and review pack",
    ),
    "pipeline/aws/r1/rk6b_rank.py": (
        "f6e206fe90a3334d4ffc9351149f002c2e01669dec2dd15cc6a5176c0bfc3864",
        "the R1 own-field ranking: 187 control gate, RK6a equivalence gate, then the author-signed own-field rule",
    ),
    "pipeline/aws/r1/verify_inputs.py": (
        "3153464f25f9fea79711da399aa081b9bc98650cf3eb4c5a7b7523cd52f425ad",
        "the R1 instance-side input checks: folder manifests for the pins, data_sync against the pins, recovered RK inputs against manifest.tsv",
    ),
    "pipeline/aws/r1/build_env.sh": (
        "34669f84ed78f6016baf96362da5c4908310896bfc32e5d3319861403b999c88",
        "the R1 environment builder: py venv, the two pinned R stacks, texlive-2025; packs and uploads r1/env/ layers",
    ),
    "pipeline/aws/r1/install_stack.R": (
        "08b0bf0fd2c8e684f24c2d73139522c3f31f683662fc8bbce15ed5a72a537882",
        "the R1 R-stack installer: renv.lock for rmac, exact versions for rcloud, polars at the lock's GitHub sha",
    ),
    "pipeline/aws/r1/versions_check.py": (
        "756cae269ba897fa387bacdb1da1c057f436fa0f061e614c47dcc9644393727d",
        "the R1 boot version check: py pins, both R stacks, pdfTeX/texlive and style files; drift stops the boot",
    ),
    "pipeline/aws/r1/run_stages.py": (
        "e6eafafcffc86a961e3d446f14d7acb394cf48cd148702cf9c0a8f4c60fba4d6",
        "the R1 multi-stage driver: per-stage status, fingerprints, products and done markers pushed under r1/runs/<job>/stages/",
    ),
    "pipeline/aws/r1/run_cells.py": (
        "592cab4f5f658ae58354bf274b6ebad1010b68dcc042bcfe2dc90ab14c3030ca",
        "the R1 estimation-cell runner: one Rscript per cell under its pinned stack, renamed to the gold name, compared",
    ),
    "pipeline/aws/r1/check_pin.py": (
        "fa6dec6ae10c13fb577cd7e08c5075233eac1077277fee04d000abf1025e6aa1",
        "the R1 pin check: a file rebuilt on AWS equals its sha/bytes pin in a committed build report, with one link",
    ),
    "pipeline/lib/r1_config.py": (
        "75172b1a13c18aab2931311cda7a207e54104a7f4d092d6447e7a6532599b3bd",
        "R1 F9 run-config loader (sar.r1.run_config.v1): frozen switch registry, required rulings, STOP codes, cross-checks against the signed lists; October-callable library read through $SAR_R1_CONFIG, on the B0 chain",
    ),
    "pipeline/aws/r1/config_check.py": (
        "272fb48161c47cbe8c5d3f3f9b884ad339743402a371a9fc2a52376ae532a767",
        "R1 F9 instance CLI: check --config --out loads the run config through pipeline/lib/r1_config.py and writes resolved.json + config_report.json (codes and counts only); exit 3 with the ConfigStop code",
    ),
    "pipeline/aws/r1/sandbox.py": (
        "69245139f0505df496d830d7d6d36ddfcbd500c627f13731b0e4329e37f84d9c",
        "R1 F2 sandbox (instance-only, stdlib): purge moves every October product to the read-only /work/ref/october and write-protects plus fingerprints base inputs; an inotify watcher logs per-stage reads of the 08-28 canon and the reference copy; check stops the job on a rewritten base input or a non-allowlisted read",
    ),
    "pipeline/aws/r1/gates.py": (
        "21b9fbd2915a0d814ae3bd15a06c6d8458f3a807bd9a0dc81d8ae815693bd40e",
        "R1 F23 instance CLI + comparator library: gate 1 (B0 only: 29 golds compare_json EQUAL in exact/ec2 mode from JP, every October product under its gate1_rules.tsv rule, cell custody vs frames MANIFEST, sandbox verdict), the J1a gate1 link and M-cell custody; repo-authored, not ported",
    ),
    "pipeline/aws/r1/run_config.py": (
        "cbf04bf0baf7b95d480e63ac790e07e8f07820ddfe5d8e137e61377d264aa75f",
        "R1 F23 instance CLI: runs one step of config/r1/chain.json (October's B0 chain) per J0 stage row inside the F2 sandbox; stdlib only, copied to /work by run_stages",
    ),
    "pipeline/aws/r1/restore_upstream.py": (
        "866b1c3e847e7fe9a5b1a0c7f79aacc81e08c79d10947f917d56b9e97301d8ed",
        "R1 instance CLI (V3-FINAL): lays out upstream J1a/J1b stage-set products for J1b restore_j1a and FINAL canon, digest-checking every token against its .done.json marker before copying anything",
    ),
    "pipeline/aws/r1/replay_derivations.py": (
        "4a92ae0e0bd5c206e1cc8dd7c7c261446525ab685d05daece0ef32e711a6634b",
        "R1 instance script for job kind recder (V3-REC): re-lifts the 13 10-02 heredoc bodies from the recorded command history, stops LIFT_DRIFT unless byte-equal to the reviewed copies, runs only the python bodies with python -I in fresh folders, and gates the RK4/RK5 payload byte copies, census 845/70 and the named 0.718",
    ),
    "pipeline/aws/r1/dossier_pack.py": (
        "05fbafa8a16cb7e0c170b4effd0ffd04e3924dd1dcc2891f7e1fb75eb615b96d",
        "R1 J0-MEAS.3e instance-side dossier builder: picks ACCEPT rows with no R1 rounds or RK4 two-round cleaning plus the named h8/h10/u2 ids, dumps each person's works up to Y from the 11-school table with prior exclusions marked; repo-authored, runs only on ec2-r1 from /work",
    ),
    "pipeline/aws/r1/rank_r1.py": (
        "b2cc74031f8c006b88e97d983ac4d44dcf38f1a709314d15ddd5938a35ae5d5d",
        "R1 V3-RANK/J0-MEAS.3d rank gate (stdlib, EC2 only): holds the unedited RK6b re-run content-equal to the pinned rk6b reference plus named asserts (gate), proves a paper-check rerun moved only allowed persons (diff), and collects the rankrepro stage results",
    ),
    "pipeline/aws/r1/restake_r1.py": (
        "31867ffb258d5f3b5d2f7c29b2b89ca6128c36fce58b6762ac408fea9f6895af",
        "R1 F17/J0-MEAS.3f/3g rank tables (EC2 only): B0 byte-copies October's MANIFEST-pinned restake_econ11/verdicts tables; M joins the signed verdicts to the gated ranks with decision-4 top-5% flags and STOP checks",
    ),
    "pipeline/aws/r1/verdict_source.py": (
        "009ab1c8ba4757b8bf44a45528e26d5a4e84b61d51b86528534199b2b556c9a3",
        "R1 F16+N1 verdict-source adapter: B0 = October write_events semantics byte for byte, M = signed rank tables with VerdictMissing STOP; imported by events_r1, stage.py, econ920_m, D7",
    ),
    "pipeline/aws/r1/calls_lib.py": (
        "c05666602c61ae1c0312b1689fea0dd1f9c00e88f90d50903475bd0e56d0f5d7",
        "R1 F8 call sets: B0 = October's historical+October calls (dose_excludes empty); M = the J1a in6 requests expanded on aw_raw by rk6b_rank.pass_b_cleaning, dose_excludes = not-this-person works minus dose_keep_r1.csv minus add pairs (instance stage calls)",
    ),
    "pipeline/aws/r1/events_r1.py": (
        "cd82844e6e5af3d7f2caa12d2d25e2ca2c81e3041ef0cf753c5139f51928c440",
        "R1 F10 + N16-S14 instance script (EC2 only): writes the M event tables and top-5% subsets in October's basenames from the signed verdicts (verdict_source), the signed redates, A5110738002's restored 08-28 line and the add-list ACCEPT rows; --mode b0 rebuilds October's six tables byte for byte",
    ),
    "pipeline/aws/r1/patch_assemble.py": (
        "d40ac0eb8e9e946ce094aff78737a96643dd20aa832de7966b87e900445a112c",
        "R1 F18 instance stage (no network): turns the OpenAlex pages the Mac fetched and uploaded under r1/patch_raw/<tag>/ into works_by_author_supplement_r1.jsonl through October's patch_row, checking each page against its committed upload record and refusing persons already in a known patch",
    ),
    "pipeline/aws/r1/missing_persons.py": (
        "914c4fddf2ca850abf46b340eae7da5acb8e093c56a4a7f6ea52db43e905041e",
        "R1 N3/J0-MEAS.3i: missing-outcome persons (econ agg_missing_r1 with explicit units/patch paths, chem/maths coverage on the 20_rebuild_y_gold aggregate key), the report|stop gate and the coverage_chemmath stage CLI; repo-authored",
    ),
    "pipeline/aws/r1/r1_dose_excl.py": (
        "2e47a561cd4d683dfe3455068ac81a7bc201ad9be087ba47507f8d42eebcda61",
        "R1 F13/S6 econ dose exclusions library: takes each star's and colleague's not-this-person works out of the topic dose of the M econ pre-y frame (delta mode, self-checked against the stored dose to 1e-12; mode off reads and writes nothing); B0 never calls it",
    ),
    "pipeline/aws/r1/edge_table.py": (
        "078de31cd977a7ce9a43463eeb8449b33d935dfd0f72380d057cdbd0440056d6",
        "R1 N2 (J1a path): shadow ssd_root that stages u1_full_11school_2026-07-16 under the u1_edges_full_2026-07-05 name for the chem/maths M build (switch chemmath_edges); env_for/CLI give SAR_PATHS_CONFIG; no pinned file edited",
    ),
    "pipeline/aws/r1/network_freeze.py": (
        "c78ec8c334742db751687e7e9fc0c4f6195ce5400fea83bc1bf7e305aed74494",
        "R1 V3-NET (C5): classifies each network relation (deg1 / deg2_frozen / deg2_unfrozen / none) by replicating prodlib.build_subgraph + build_pairs in SQL on the builder's graph, and filters the network frame byte-preservingly before the union rung (drops the deg-2 unfrozen arm; STOPs with ids on an unexplained relation); never imported by the October chains",
    ),
    "pipeline/aws/r1/mem_probe.py": (
        "3849d5862228f8e536de0a5076278227a27e8d3d7138fbbd974f09c198bdf7e9",
        "R1 J0-MEAS.3k J1a stage: measures the P3 frame rows and the peak RSS / wall time of one permutation and one null unit per field under the rcloud stack and October's thread setting; writes mem_report.json (sar.r1.mem_probe.v1) for the N8 planner",
    ),
    "pipeline/aws/r1/promote_r1.py": (
        "b15210a117d136049d7ed57a1caf01ec19d6d8eb202bf0c96e1262cf2f09fdae",
        "R1 F4 J1a stage promote: packages the assembled M frames and the 27 gold-row cell estimates into STAGE_OUT/{frames,expected} with bare-name MANIFESTs, SOURCES.md and expected_refreeze_r1.json (October side read-only from /work/ref), plus the post-promotion custody check; October's promote.py is untouched",
    ),
    "pipeline/aws/r1/rob_jobs_r1.py": (
        "d3b47a5f5192af174f813be66f6a4dfe276e5b8b3d4d66718cf19e26071c329f",
        "R1 J1b robustness job-list builder (F19): units.tsv in groups frames/cells/loeo/perm/null/post from config/r1/robustness_r1.json, M or October mode, with the P05 coverage, forbidden-path and unset-input STOPs; its sha256 is the joblist digest the N8 plan carries",
    ),
    "pipeline/aws/r1/run_units.py": (
        "a584d0b4b9051be274def024b022ea544575507910ef8a9a2161ba7e43ac8648",
        "R1 J1b unit executor (F19, stdlib): runs one group of units.tsv at the N8 plan's width and threads, records estimator failures and lets the batch continue, stops at once on OOM or a control mismatch, runs post units serially",
    ),
    "pipeline/aws/r1/rob_post_r1.py": (
        "f687af027de18098b357e0e4ce2ee9180ceafd156e1c7a8fdad52f0f39da3fc2",
        "R1 J1b robustness post and build steps (F19): LOEO ranking, A_far cut grid, permutation summaries, null merges, cut builds, no-centre report, manifests and custody; each proven byte-equal to its October product in October mode",
    ),
    "pipeline/aws/r1/run_robustness_r1.sh": (
        "6199fb3c91c3b0b0676015aceb971c3881cd4d8a59c6356e7f39a803dc0446b7",
        "R1 J1b stage entry (F19): bash run_robustness_r1.sh <jobs|frames|cells|loeo|perm|null|post> copies the robustness scripts to WORK/bin and runs that group with ROB_ROOT inside the clone (the robustness tree under the repo output root)",
    ),
    "pipeline/aws/r1/par_plan.py": (
        "46761b614458c07c16c682486aa2715df49cb37e8ebe2bf080b4159b58d43f5c",
        "N8 memory-aware parallel-width planner: first J1b stage, reads rob_jobs unit TSV + J1a mem_probe report, writes plan.json (PAR/threads per group, STOP above 450 GiB, split_after for two-launch J1b)",
    ),
    "pipeline/aws/r1/fig4_counts.py": (
        "625f8af25ce1962d456b984977636e3b183d86e434d0744d02db78658f6666e0",
        "R1 N5 instance CLI: counts Figure 4 comparison relations per model/channel/cohort/year from run_save_sample.R's save_sample files by the author's 2026-10-03 rule (figB.py parity test) and cross-checks the switcher tags against the estimator's Switchers column",
    ),
    "pipeline/aws/r1/econ920_m.py": (
        "2e10efe623138266bec3906eac1431d8cce9230ca79e8044915eb383a2c5e394",
        "R1 F11 (+F13 hook, J0-MEAS.3h/3i, V3-NET hook): J1a stage frames_econ920 - economics for run config M through October's econ920 machinery (run_econ920 / econ920_lib imported, never edited): October's controls c1a/gdose/c1b/c2/c3 in the same root, then a plan read from the data (removed_old, REGEN = id-corrected + re-dated + new events in one prodlib run, A5110738002 restored), the ledger re-dated in place, the M star set, V3-NET on the clone's input, the evidence-gated G-DOSE measurement, the incumbent-star rule, the agg-missing gate, the S6 dose post-step and the chain without the split stage; writes only under STAGE_OUT",
    ),
    "pipeline/aws/r1/chemmath_m.py": (
        "b0b03dd97f3e1534f63367bd0b89680fcb79fde141da5bd9741d79f8751ac596",
        "R1 F14 + J0-MEAS.3h: the M chemistry/mathematics frames driver (J1a stage frames_chemmath_m; J1b nocentre with --roster-variant incfel). Config/pin preconditions, M stars_excluded rule, stage.build_shadow with the M list and rosters, N2 env check, prodlib, D2, V3-NET, the October chain plus a post_union dose hook, G-DOSE advisory copy, coverage gate, products per field; --mode b0 reproduces data/cal2026-10/frames_<field>/ (switch-off proof)",
    ),
    "pipeline/aws/r1/dose_chemmath.py": (
        "a6b7cb89a3b4c672eb48bcf842ed40794b179171b148be85c2fa8005479ba8b6",
        "R1 F14 (S6, chemistry/mathematics): delta dose post-step on the union frame. Removes not-this-person works and adds split-id works back into the star vectors. Network/both rows use the prodlib rule, dept_only rows the union-builder rule. The exact-text CONTROL STOPs on a mismatch. Only the dose_topic cell is rewritten, with a closing proof",
    ),
    "pipeline/aws/r1/reverse_proof_s10.py": (
        "1d5f65ca8099a6152dfac1a4fdd82f32a1df09ab3347a0ca480940eac6529996",
        "R1 J0-MEAS.3j / S10 reverse proof (N2's real-data test, big host B4, not a J0 stage): cuts u1_full_11school_2026-07-16 to the 07-05 works and checks the content premise, runs chemmath_m.py --mode b0 through edge_table's shadow (cut / full-table / wiring runs), compares to October under the October acceptance rules and checks the roster channel up to the age-gap guard; writes only under --out, summary ids/counts only",
    ),
    "pipeline/aws/r1/final_stage.py": (
        "60439e48db848f4733fec9a04834891c9115abab48c03e61eece7723a86c41c1",
        "R1 final job driver (V3-FINAL): unpack, canon, paper, sentinel, repin, compile, texts, red, numbers and gate2 subcommands for the final (M) and finalb0 (October twin) jobs",
    ),
    "pipeline/aws/r1/v3net_oracle_spec.py": (
        "8db84451177ac280266e6d2d1c5d17ef11aeacabb666ccd620d2d7a0a42bc894",
        "R1 batch B4 (t-big-04): rebuilds October's V3-NET oracle inputs in config B0 with the chemmath_m / econ920_m functions and writes the sar.r1.v3net_oracle_spec.v1 spec that tests/test_r1_network_freeze_real.py reads",
    ),
}
#: pinned like every other count here, so a new declaration cannot be one appended line
#: cal2026-10 (2026-09-23): 51 -> 83, the 32 repo-authored files of pipeline/frames/cal2026-10/**,
#: pipeline/rosters/cal2026-10/ and pipeline/stars/caliber_2026-10/ (every one listed by
#: tools/verify_ported.py as ADDED before this registration)
#: R1 wave 1 (2026-10-16): +2 by hand for analysis/robustness/figure4/{run_save_sample.R,README.md}
#: (outside pipeline/, so not in N_PORTED_MANIFEST); the pipeline/ files follow via tools/r1_register.py (not shipped)
N_REPO_AUTHORED = 132
#: the only directories a repo-authored `.py` may sit in, and only DIRECTLY in them - never in a
#: driver run directory, which becomes sys.path[0] for a direct script invocation
REPO_AUTHORED_CODE_DIRS = ("pipeline/lib/", "pipeline/frames/", "pipeline/drivers/",
                           # T4: the ported FWCI scripts sit one level deeper, in
                           # `<run directory>/code/`, so `pipeline/fwci/` is never the
                           # sys.path[0] of a direct script invocation.
                           "pipeline/fwci/",
                           # T5: same shape - the ported roster scripts live in
                           # `<run directory>/{code,verify}/`, two levels down.
                           "pipeline/rosters/",
                           # T6: same again - `<run directory>/code/` and, for the ranking machine,
                           # `<run directory>/code/star_screening/`, three levels down.
                           "pipeline/stars/",
                           # cal2026-08-28: the caliber layer - repo-authored code beside, never
                           # inside, the ported run directories.
                           "pipeline/stars/caliber_2026-08-28/",
                           # cal2026-10: the runnable AWS launcher and its local half — a
                           # directory with no ported script, so never sys.path[0] of one.
                           "pipeline/aws/cal2026-10/",
                           # cal2026-10 (2026-09-23): the October caliber layers — repo-authored
                           # code beside the ported run directories, never inside one; each of
                           # these directories holds no ported script, so none is ever the
                           # sys.path[0] of a ported invocation.
                           "pipeline/stars/caliber_2026-10/",
                           "pipeline/rosters/cal2026-10/",
                           "pipeline/frames/cal2026-10/",
                           "pipeline/frames/cal2026-10/econ_gold/",
                           "pipeline/frames/cal2026-10/econ920/",
                           # R1 (2026-10-11): the AWS rerun kit - launcher, boot template
                           # and the instance-side job scripts; no ported script lives here.
                           "pipeline/aws/r1/")

#: imported run evidence, kept as a prefix rule because it is 30 files of logs and fetched JSON.
#: Executable code may not hide in it: the test asserts nothing under here is a .py file.
REPO_AUTHORED_PREFIXES: tuple[str, ...] = ("pipeline/aws/logs/",)


def test_repo_authored_entries_are_pinned_counted_and_shaped():
    """T2 re-review R2. `REPO_AUTHORED` is the partition's escape hatch, so it carries the same locks
    `ADDED` had - plus two the driver layer needs, because this is the half of `pipeline/` that
    `PORTED` does not map and where a script directory becomes `sys.path[0]`."""
    assert len(REPO_AUTHORED) == N_REPO_AUTHORED, (
        f"{len(REPO_AUTHORED)} declarations, ledger says {N_REPO_AUTHORED}. A new repo-authored file "
        f"under pipeline/ must move the count in the same commit.")
    for rel, (want, why) in sorted(REPO_AUTHORED.items()):
        f = REPO / rel
        assert f.is_file(), f"{rel} is declared REPO_AUTHORED but is not in the tree"
        assert len(why.strip()) > 30, f"{rel}: a declaration needs a real reason"
        got = _sha(f.read_bytes())
        assert got == want, (
            f"{rel}: content changed since it was declared.\n  declared {want}\n  actual   {got}\n"
            f"Update the pin in the same commit as the edit - these are the layer's own guard, "
            f"launcher and documentation, and they are not reviewed by the verbatim tests.")
        assert not _is_auto_executed(rel), (
            f"{rel}: Python executes this basename with nobody importing it. A repo-authored file "
            f"may not be auto-executed - that is the F1 hole, and it is not reopening here.")
        if rel.endswith(".py"):
            parent = rel.rsplit("/", 1)[0] + "/"
            assert parent in REPO_AUTHORED_CODE_DIRS, (
                f"{rel}: repo-authored code may only sit DIRECTLY in {REPO_AUTHORED_CODE_DIRS}. A "
                f"`.py` in a driver run directory would load first for a direct script invocation.")
            stem = rel.rsplit("/", 1)[1][:-3]
            assert stem not in sys.stdlib_module_names, (
                f"{rel}: '{stem}' is a standard-library module name. On `sys.path[0]` this shadows "
                f"the real one for every script in that directory (T2-review F2).")


def test_no_file_under_pipeline_shadows_a_stdlib_module():
    """Belt to R2's brace, over the WHOLE layer rather than just the declarations: no `.py` anywhere
    under `pipeline/` may be named after a standard-library module, ported or not. The ported tree
    happens to be clean, and the verbatim tests would catch a change there - this makes the property
    explicit instead of incidental."""
    hits = []
    for f in _walk(REPO / "pipeline"):
        if f.suffix != ".py":
            continue
        if f.stem in sys.stdlib_module_names:
            hits.append(f.relative_to(REPO).as_posix())
    assert hits == [], f"stdlib-shadowing module(s) under pipeline/: {hits}"


def _load_launcher():
    """Import `pipeline/drivers/run_driver.py` as a module so its DRIVERS map can be INSPECTED.

    T2 final review R5: the previous version of this test was a substring search over the file, and
    the launcher's own 25-line docstring contains `output_target()`, `runpy`, `U6_OUT` and all five
    driver names. Emptying `DRIVERS["step3"][1]` and refreshing one sha pin left every test green
    while removing the only control step3 has. Text cannot prove a data structure; the structure can.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sar_run_driver", REPO / "pipeline/drivers/run_driver.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_launcher_registers_and_checks_every_driver():
    """Asserted on the imported object, never on the source text."""
    rd = _load_launcher()
    assert set(rd.DRIVERS) == {"step1", "step2", "step3", "step4", "u3"}, sorted(rd.DRIVERS)

    # step3 is the ONLY driver with no in-port protection, so its registration is pinned exactly.
    assert rd.DRIVERS["step3"][1] == ("U6_OUT",), (
        "step3's output constant is not registered with the launcher. step3 calls "
        "run_u6.run_all(..., force=True) and nothing inside the port can stop it - the launcher is "
        "its only control.")

    # Every driver either declares an output the launcher resolves, or is declared self-guarding
    # WITH a reason, and a self-guarding claim has to be true in the driver's own source.
    for name, (script, consts) in sorted(rd.DRIVERS.items()):
        target = REPO / "pipeline/drivers" / script
        assert target.is_file(), f"{name}: registered script {script} does not exist"
        if consts:
            assert all(isinstance(c, str) and c for c in consts), f"{name}: bad constants {consts}"
            continue
        assert name in rd.SELF_GUARDED, (
            f"{name} declares no output constant and is not in SELF_GUARDED - it would run "
            f"completely unchecked, and `--list` would show it as a blank row.")
        assert len(rd.SELF_GUARDED[name].strip()) > 30, f"{name}: SELF_GUARDED needs a reason"
        src = target.read_text(encoding="utf-8")
        assert any(g in src for g in ("_sar_out(", "_sar_lazyout(")), (
            f"{name} is declared self-guarding but its source wraps no destination in the write "
            f"barrier - the claim is false.")

    # A driver script that nobody registered gets no check at all.
    assert rd.unregistered_scripts() == [], (
        f"driver script(s) not registered in DRIVERS: {rd.unregistered_scripts()}")


def test_the_launcher_names_no_machine_specific_path():
    assert not ABS.search((REPO / "pipeline/drivers/run_driver.py").read_text(encoding="utf-8"))


# --- T4: the FWCI launcher, asserted the way T2's final review demanded ---------------------------
def _load_fwci_launcher():
    """Import `pipeline/fwci/run_fwci.py` as a module. Same reason as `_load_launcher`: T2 final
    review R5 showed a substring search over a launcher's source is satisfied by its own docstring."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sar_run_fwci", REPO / "pipeline/fwci/run_fwci.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_fwci_launcher_registers_every_ported_script_and_gates_the_expensive_one():
    fw = _load_fwci_launcher()
    assert set(fw.STAGES) == {"build", "scan"}, sorted(fw.STAGES)

    # The 37-minute full-snapshot scan is the ONE stage the plan forbids running.
    assert fw.STAGES["scan"][3] is True, (
        "the scan's gate is gone. Without it `run_fwci.py scan` runs a 37-minute pass over 665.7 GB "
        "of works shards with no warning.")
    assert fw.STAGES["build"][3] is False, "the cheap build stage must not be gated off"

    for name, (script, outputs, modules, _gated) in sorted(fw.STAGES.items()):
        assert (REPO / "pipeline/fwci" / script).is_file(), f"{name}: {script} is not in the tree"
        assert outputs and all(o.startswith("data/") for o in outputs), (name, outputs)
        assert modules and all(len(m) == 2 for m in modules), (name, modules)

    # a ported script nobody registered would run with no gate and no staged output location
    assert fw.unregistered_scripts() == [], fw.unregistered_scripts()

    # the scratch root's BASENAME is load-bearing: the ported preamble finds the repo by walking up
    # to a directory named "fwci", and $SAR_OUT_ROOT redirects to <root>/<basename>.
    assert fw.SCRATCH.name == "fwci", fw.SCRATCH
    assert fw.SCRATCH.parent == REPO / "output", fw.SCRATCH


def test_every_figure_in_the_scan_cost_gate_comes_from_a_frozen_record():
    """T4 review NIT-1, promoted. The gate used to be a literal, and the reviewer falsified SIX of its
    eight numbers - the worker count, the shard count, the streamed bytes, the throughput, the cell
    count, the merge time, and both funnel figures the paper cites - while keeping the two substrings
    a test pinned. `97 passed`, `REPIN_OK`, nothing noticed.

    So the numbers are no longer written in the launcher: `_scan_cost()` reads them from
    `data/fwci/scan_manifest.json` and `data/fwci/scan_full_2026-08-09.log`, both sha256-pinned in
    `data/MANIFEST.sha256`. This test re-derives every one of them from those files INDEPENDENTLY
    (its own parsing, not the launcher's), requires each to appear, and then sweeps the whole string
    for any number that cannot be traced back - so neither a changed literal nor a swapped field
    survives."""
    import json
    import re
    fw = _load_fwci_launcher()
    fwci = REPO / "data" / "fwci"
    m = json.loads((fwci / "scan_manifest.json").read_text())
    log = (fwci / "scan_full_2026-08-09.log").read_text()
    cost = fw._scan_cost()

    # every quantity, re-derived here from the record rather than read out of the launcher
    traceable = {
        "runtime min":     re.findall(r"scan done in ([0-9.]+) min", log)[-1],
        "workers":         re.findall(r"workers=(\d+)", log)[-1],
        "gz GB":           f"{int(re.findall(r'gz_bytes=([\d,]+)', log)[-1].replace(',', '')) / 1e9:.1f}",
        "throughput":      re.findall(r"cum=[\d,]+ ([\d,]+) rec/s", log)[-1],
        "merge min":       str(m["merge_elapsed_min"]),
        "partial tables":  str(m["n_partials"]),
        "shards":          f"{m['shards']:,}",
        "records":         f"{m['total_lines_read']:,}",
        "benchmark cells": f"{m['n_cells']:,}",
        "cellable works":  f"{m['sum_work_count']:,}",
        "citations":       f"{m['sum_citation_sum']:,}",
        "bad lines":       str(m["bad_lines"]),
        "snapshot date":   m["snapshot_manifest_date"],
    }
    for what, value in traceable.items():
        assert value in cost, f"the cost gate no longer states the {what} ({value}):\n{cost}"

    # …and nothing in it is a number the record does not support
    allowed = set()
    for value in traceable.values():
        allowed.update(re.findall(r"\d[\d,]*(?:\.\d+)?", value))
    PROSE = {"3", "256"}      # "about 3x slower" (an estimate, stated as one) and "sha256"
    untraceable = [tok for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", cost)
                   if tok not in allowed and tok not in PROSE
                   and tok not in {"2026", "08", "09"}]     # the frozen file names carry their date
    assert untraceable == [], (
        f"number(s) in the cost gate with no source in the frozen record: {untraceable}\n"
        f"Every figure the warning prints must be read from data/fwci/, not written here.\n{cost}")

    # the two figures that are also thesis numbers must match the thesis ledger's own values
    from analysis.paper import ledger_funnel
    assert f"{ledger_funnel.THESIS_VALUES['works_benchmarkable']:,}" in cost
    assert f"{ledger_funnel.THESIS_VALUES['works_snapshot']:,}" in cost


def test_the_scan_cost_gate_fails_loudly_if_its_record_stops_saying_the_number(tmp_path,
                                                                              monkeypatch):
    """The derivation must not silently degrade to 'no figure' if the log changes shape."""
    fw = _load_fwci_launcher()
    stub = tmp_path / "scan_full.log"
    stub.write_text("[scan] shards=1 manifest_records=1 gz_bytes=1\n")   # no 'scan done in' line
    monkeypatch.setattr(fw, "SCAN_LOG", stub)
    with pytest.raises(SystemExit, match="the measured runtime is not in"):
        fw._scan_cost()


def test_the_fwci_scan_stage_refuses_to_run_without_an_explicit_flag():
    """Behaviour, not declaration: the process must exit non-zero and print the cost."""
    import subprocess
    staged = REPO / "output/fwci/fwci_baseline_fullsnapshot_2026-08-09"
    before = staged.exists()          # a previous --execute run may legitimately have left one
    r = subprocess.run([sys.executable, str(REPO / "pipeline/fwci/run_fwci.py"), "scan"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "OFF by default" in r.stderr and "37.0 minutes" in r.stderr, r.stderr
    assert "510,372,821" in r.stderr and "665.7 GB" in r.stderr, r.stderr
    assert staged.exists() == before, "the refused stage staged a run directory anyway"


def test_the_fwci_scratch_root_is_judged_by_the_write_barrier(monkeypatch):
    """$SAR_OUT_ROOT moves the scratch root, so it must be barred from pointing at a legacy tree -
    the exact hazard T2's re-review found open for the drivers (R1)."""
    fw = _load_fwci_launcher()
    from pipeline.lib.paths import WriteBarred, legacy_thesis
    if not legacy_thesis().is_dir():
        pytest.skip("legacy tree not on this machine")
    monkeypatch.setenv("SAR_OUT_ROOT", str(legacy_thesis()))
    with pytest.raises(WriteBarred):
        fw._stage_run_dir("build")


def test_the_fwci_launcher_names_no_machine_specific_path():
    assert not ABS.search((REPO / "pipeline/fwci/run_fwci.py").read_text(encoding="utf-8"))


def test_run_u0p5_write_root_is_behind_the_barrier():
    """T2 re-review R3: a ported UNIT that writes. `run_u0p5` is a live CLI whose write root is the
    frozen, non-empty `<derived>/u0p5_roster`. Only the WRITE root is guarded - a read guard would
    raise at import and T1 measured that this makes the ported suite uncollectable without the SSD."""
    src = (REPO / "pipeline/units/u0p5_dept_roster/src/roster/run_u0p5.py").read_text("utf-8")
    assert 'SSD_DERIVED_DIR = _sar_lazyout(_sar_derived_root() / "u0p5_roster")' in src
    assert "_sar_rd(" not in src, (
        "run_u0p5 must NOT guard its read roots: require_readable raises at import and the ported "
        "suite then cannot be collected without the data disk (T1 measurement, 15 collection errors)")


# --- files RECOVERED from the author's working records ------------------------------------------
# Twelve producers in this chain were never saved as files in any surviving tree: they were written
# into a temporary working directory the OS has since reclaimed, or ran once as a heredoc inside a
# shell command. They survive in the author's private working records (a log of every file write,
# edit and shell command), and were re-derived by replaying the recorded operations - reading shell
# patches rather than executing them. The replay and its check against those records run in the
# author's private repository; the records themselves are not part of this package.
#
# These files are therefore NOT ports of a surviving file; they are REPLAYS, pinned by the sha256
# below and by their symbolic form in tests/pipeline_symbolic.sha256. The proof that a replay is the
# ORIGINAL and not a plausible substitute is external and empirical: `merge_roster.py` rebuilds the
# frozen 920-row econ roster byte for byte, `build_audit.py` rebuilds its 994-row audit table and all
# 22 batch files byte for byte, and the incfel body rebuilds both incfel rosters content-equal (see
# tests/test_pipeline_rebuild.py, author-only).
#
# repo path -> (label of the private working record, basename replayed towards OR "",
#               inline command timestamp OR "", preamble blocks injected, sha256 of the REPLAY, why)
# Public copy: where a replay with 0 preamble blocks had person names removed from its text, the
# sha256 is that of the published file; the private value is listed in HASH_CROSSWALK.md.
RECOVERED: dict[str, tuple[str, str, str, int, str, str]] = {
    "pipeline/rosters/econ_roster_verify_2026-08-09/code/merge_roster.py": (
        "private record A", "merge_roster.py", "", 1,
        "a59c36434def7b45156b0ea6f42363b1557e8a9de55a9e275498730e50ef9983",
        "the economics roster merge: 22 human-returned batches + the 994-row audit table -> the "
        "frozen 920-row roster. 1 Write + 9 Edit, replayed in recorded order. Its BASE constant is "
        "patched exactly like the chem/math merge's",
    ),
    # MILESTONE REVIEW BLOCKER: this one was registered as a LOST PRODUCER by the T5 fix wave - the
    # same wave that wrote the step-6 protocol and declared it binding - and the protocol was never
    # run on it. It is an inline heredoc in the SAME record the register already cites for
    # merge_roster.py, 6 s before the artifact's mtime, and it holds no absolute path at all
    # (`pd.read_csv("rejected_persons.csv")`), so it ports byte-identically with 0 preamble blocks.
    "pipeline/rosters/econ_roster_verify_2026-08-09/code/add_reject_cause.py": (
        "private record A", "", "2026-08-09T12:40:54.559Z", 0,
        "824ea2a3226ec24474436df25af86fd83dd2f1fb07c937820b85026dd6667d80",
        "the reject_cause enrichment: it maps all 74 rejected author_ids to one of four causes and "
        "inserts the column at index 6, turning the 12-column rejected_persons.csv the merge writes "
        "into the frozen 13-column one. Byte-for-byte proof in tests/test_pipeline_rebuild.py",
    ),
    "pipeline/rosters/econ_roster_verify_2026-08-09/code/build_audit.py": (
        "private record B", "build_audit.py", "", 1,
        "60f7574ede5d7e258240801008c10c2f63913ce5681b6fab4db0af07a02b621d",
        "the economics batch builder: the 994-person machine roster -> the evidence audit table and "
        "the 22 review batches. 1 Write + 2 Edit + ONE in-place shell patch that the replay reads "
        "out of the record rather than executing (executing it would have deleted 22 legacy "
        "files); skipping that patch produced a file differing from the real producer in 154 rows",
    ),
    "pipeline/rosters/multidisc_gold_2026-08-10/code/00b2_prep_incfel_variant.py": (
        "private record C", "", "2026-08-10T10:38:27.165Z", 1,
        "20e059a6aabfe825f6a0414d09764f5597f7ddd7ac90a6dcb99c4185dde85da5",
        "the missing incfel rung of the population ladder. It never was a file: it ran once as a "
        "heredoc inside one Bash call at 10:38:27 UTC, three seconds before the incfel rosters' "
        "mtime, and 00b's saved VARIANTS map has no incfel branch. The BASENAME is this repo's "
        "choice (the original had none); the body is lifted whole and unmodified",
    ),
    # --- T6 review BLOCKER-1: the event-selection rung ------------------------------------------
    # `72` re-stakes 67 candidates; `00_make_u4_aug.py` consumes 38 econ events and
    # `70_prep_fnfix_inputs.py` consumes 24 chem/math events. NOTHING on disk turns the first into
    # the second two. Both selectors ran once as a heredoc inside a Bash call and were never files,
    # which is why every on-disk search fails and why T6's first pass treated their outputs as given
    # inputs. Recovered from an inline command, and proven external to the record in the way T5's
    # `merge_roster.py` was: each re-run reproduces its frozen output BYTE FOR BYTE.
    "pipeline/stars/multidisc_gold_2026-08-10/code/00_select_new_events_chemmath.py": (
        "private record C", "", "2026-08-15T12:51:58.422Z", 0,
        "362e1e0305df68d95d530f6d429e0bcb52c9c264084c87e17ff5fc430fe8f154",
        "the chemistry/math-stats event selection: 67 re-staked candidates -> the 24 signed new "
        "events (13 chem + 11 math) plus a one-row `_wide_extra` file. It never was a file: it ran "
        "as a heredoc at 12:51:58 UTC with the working directory set to the gold run directory, "
        "which is why every path in it is relative and why it needs NO path hunk at all. The "
        "BASENAME is this repo's choice (the original had none); the body is lifted whole. Two "
        "rules live only here - the `in_window` filter that sends A5062352558 to `_wide_extra`, and a "
        "dead hard-coded `borderline` id - both documented in pipeline/stars/README.md",
    ),
    "pipeline/stars/multidisc_gold_2026-08-10/code/00_select_new_events_econ.py": (
        "private record C", "", "2026-08-15T16:04:57.679Z", 1,
        "e12a1314fa8a64758d36bf52c4034d6bf1386f65ca087efa0ab6531bce1d04a2",
        "the economics event selection: the same 67 re-staked candidates -> the 38 signed new "
        "events, dropping exactly A5027126744 (.8753) and A5105845982 (.8675). Also a "
        "heredoc, run at 16:04:57 UTC from the gold run directory; its ONE absolute constant is the "
        "econ_fnfix run directory it WRITES into, which goes through staged_run_dir() like the "
        "roster scripts' roots. Its output is the frozen data/raw_verified/events_econ_new38.csv, "
        "which the re-run reproduces byte for byte. The BASENAME is this repo's choice",
    ),
    # --- T6 FINAL review REOPEN-2: the rung ABOVE the selectors ---------------------------------
    # `fnfix_candidates_restake.csv` carries `in_window`, `arrival_true` and `arrival_roster` - the
    # input `72` re-stakes on and both selectors read - and it was never a file either. Four
    # heredocs build it by appending, in this order. The first three are runnable and reproduce the
    # frozen file's first 62 of 67 rows byte for byte; the fourth reads a deleted temporary task output
    # and is NOT_RUNNABLE (see LOST_INPUTS and pipeline/stars/README.md).
    "pipeline/stars/multidisc_gold_2026-08-10/code/00_build_candidates_restake_chem.py": (
        "private record C", "", "2026-08-15T12:31:37.988Z", 0,
        "7b9ad5749368fe3c49d5c173888105cf98855b51b0ae13f842610afe9b83cd66",
        "rung 1 of the candidate table: the confirmed chemistry recheck verdicts. This is where "
        "chemistry's `in_window` is defined - `2005 <= int(c['arrival_roster']) <= 2023` - the rule "
        "that keeps A5062352558 out of the 35 while two economists with the same 2003 arrival are in "
        "the 38. Every path in it is relative to the gold run directory it ran from, so it needs no "
        "path hunk; the BASENAME is this repo's choice",
    ),
    "pipeline/stars/multidisc_gold_2026-08-10/code/00_build_candidates_restake_math.py": (
        "private record C", "", "2026-08-15T12:37:31.739Z", 0,
        "e5eb8ef7d69aad2055cf3854ba27897b1d62560be0ac2ee9a92d19dbd7fe0247",
        "rung 2: appends the confirmed math-stats verdicts to rung 1's output, with the SAME window "
        "expression chemistry uses. Relative paths only, no path hunk; BASENAME chosen here",
    ),
    "pipeline/stars/multidisc_gold_2026-08-10/code/00_build_candidates_restake_econ.py": (
        "private record C", "", "2026-08-15T12:46:25.282Z", 0,
        "ec86d3cfef48cfc67594734e0fb68c2fdebca5172c0cbfaccaefbff088bbf507",
        "rung 3: appends the confirmed economics verdicts, and defines economics' DIFFERENT window "
        "- `1999 <= int(r['arrival_true']) <= 2024`, other bounds and a different column. This is "
        "the asymmetry the A5062352558 decision turns on. Relative paths only; BASENAME chosen here",
    ),
    "pipeline/stars/multidisc_gold_2026-08-10/code/00_build_candidates_restake_econ_u4flagged9.py": (
        "private record C", "", "2026-08-15T16:02:54.597Z", 0,
        "088ffe823e23ec26e8828269fb21d395bea27117243d25ec77da98a77ff21390",
        "rung 4: records the nine U4-flagged economics verdicts and appends the five confirmed ones, "
        "taking the table from 62 rows to the frozen 67 - with `in_window` set to the LITERAL True, "
        "no test at all, a third code path for the same column. It cannot run: its `d` comes from a "
        "deleted temporary task output, declared in LOST_INPUTS. Ported verbatim so the rule "
        "it applies is readable; BASENAME chosen here",
    ),
    # --- T7: the two frame producers recon called "no builder anywhere on disk" -----------------
    # Both are the same story a fourth and fifth time, and the plan's own search protocol is what
    # found them: recon searched the DISK for a file, and neither was ever a file. The splitter ran
    # as a heredoc at 18:15:00.361Z, whose local time 04:15:00 is the exact mtime of both frozen
    # subsets; the speed-bracket producer ran at 22:12:52.577Z = 08:12:52, the exact mtime of the
    # frozen CSV - and the attempt 18 seconds earlier is recorded in the working log as having
    # FAILED (`TypeError: unsupported operand type(s) for /: 'decimal.Decimal' and 'float'`), which
    # is why there are two candidate ops and only one of them can be the producer. Neither file
    # holds an absolute path, so neither needs a preamble block.
    "pipeline/frames/econ_fnfix_2026-08-15/code/split_old79_new38.py": (
        "private record C", "", "2026-08-15T18:15:00.361Z", 0,
        "ea63b06352c5401b28fe19c66688af8f969ea8eb4aed864b8df1bc25f2fe0e27",
        "the old79/new38 split of the P1 econ frame - plan D2 said no builder existed and recon "
        "reconstructed its RULE from the frozen bytes. The producer survives: an 11-line heredoc "
        "run with the working directory set to the econ_fnfix run directory, so every path in it is "
        "relative and it needs no path hunk. It confirms two of recon's three inferences (order-"
        "preserving partition on event_id, field text copied verbatim) and corrects the third: the "
        "CRLF does not come from a file opened WITHOUT newline='' - the file is opened WITH it, and "
        "the CRLF is csv.DictWriter's default lineterminator. The BASENAME is this repo's choice",
    ),
    "pipeline/frames/p3_topicpair_2026-08-17/code/speed_bracket.py": (
        "private record D", "", "2026-08-17T22:12:52.577Z", 0,
        "5b9cc970846b40f6ece97f88df3269c11dd47256eaa64827ef7dbb00406b598b",
        "the collaboration-speed bracket - plan D2 item (iii), the one artifact M3 was going to ship "
        "as permanently unreproducible, and the one the paper's 0.44-0.63 / 0.44-0.64 speed "
        "intervals rest on. Also a heredoc, run from the p3_topicpair run directory with relative "
        "paths only. Its nine input cells are legacy intermediates: three are the frozen A_far "
        "panels, three more come from the same 50_leftbehind_build.py this task ports, and three "
        "(pairs_slim_cap_*_ALL) come from 90_capped_build.py, which is NOT ported. The BASENAME is "
        "this repo's choice",
    ),
}
N_RECOVERED = 12


# --- T2: the two declared, deliberate exceptions --------------------------------------------------
@pytest.mark.parametrize("rel", sorted(LOST_INPUTS))
def test_lost_input_paths_are_declared_and_still_present(rel):
    """A verbatim path pointing at a location that no longer exists is kept, not repointed. It must
    be declared, and the declaration must still match the file."""
    marker, why = LOST_INPUTS[rel]
    text = (REPO / rel).read_text(encoding="utf-8")
    assert marker in text, f"{rel}: declared lost-input marker {marker!r} is gone - update LOST_INPUTS"
    assert len(why.strip()) > 60, f"{rel}: a lost input needs a real explanation"


def test_step4_export_destination_is_behind_the_write_barrier():
    """T2-review F3. `step4_export_r.py` targets the read-only legacy thesis tree, and it truncates:
    `open(out, "w")`, no existence check. The port keeps the destination truthful - that is where the
    July artifact went - and makes it unwritable instead, in the RESOLVER, so no driver logic is
    edited. A prose 'do not run' beside a runnable `if __name__ == "__main__":` is not a mechanism."""
    sys.path.insert(0, str(REPO))
    from pipeline.lib.paths import is_inside_legacy, legacy_thesis, WriteBarred, BarredWriteTarget
    dest = legacy_thesis() / "v2_output" / "r_p10_80ev_2026-07-22"
    assert is_inside_legacy(dest) is not None, "legacy_thesis is not registered as a legacy root"
    common80 = (REPO / "pipeline/drivers/final80_p10_2026-07-22/common80.py").read_text("utf-8")
    assert "_sar_lazyout(pathlib.Path(" in common80, "R_PKG is no longer behind the write barrier"
    assert 'str(_sar_legacy_thesis()) + "/"' in common80, "the destination is no longer truthful"

    if not legacy_thesis().is_dir() or "SAR_OUT_ROOT" in __import__("os").environ:
        pytest.skip("needs the legacy tree present and $SAR_OUT_ROOT unset")
    from pipeline.lib.paths import deferred_output_target
    barred = deferred_output_target(dest)
    assert isinstance(barred, BarredWriteTarget) and str(barred) == str(dest)
    with pytest.raises(WriteBarred):
        (barred / "data").mkdir(parents=True, exist_ok=True)


def test_the_u3_driver_output_is_behind_the_write_barrier():
    """T2-review F5: the U3 driver calls `build_panel(..., resume=False)` against a FROZEN artifact
    whose input view still exists, so the documented command really would rewrite it."""
    u3 = (REPO / "pipeline/drivers/u3_run/run_u3_rebuild_f123_2026-07-06.py").read_text("utf-8")
    assert "_sar_out(_sar_rw(_sar_derived_root())" in u3, "OUT is no longer behind the write barrier"
    assert "resume=False" in u3, "the ported build_panel call was altered"


@pytest.mark.parametrize("const", sorted(NO_PRODUCER_INPUTS))
def test_inputs_without_a_producer_are_declared_and_still_referenced(const):
    """T2-review F4: two inputs the ported step1 reads have no builder in any tree, and were first
    filed as 'a skipped driver would add this'. They are gaps; the declaration must not rot."""
    rel, why = NO_PRODUCER_INPUTS[const]
    assert const in (REPO / rel).read_text(encoding="utf-8"), (
        f"{const} is no longer referenced in {rel} - remove the stale NO_PRODUCER_INPUTS entry")
    assert len(why) > 200, f"{const}: a no-producer entry needs the evidence and a check-instead"
    readme = (REPO / "pipeline/drivers/README.md").read_text(encoding="utf-8")
    assert const in readme and "gap register" in readme, (
        f"{const} is not in drivers/README.md's gap register")


def test_no_absolute_paths_left_in_the_port():
    """The whole point of the path hunks: nothing under pipeline/ names the author's machine.
    Scans the entire layer, not just the ported roots - config/paths.yaml is the only place a
    machine-specific path may appear in this repo."""
    hits = []
    for repo_rel in ["pipeline"]:
        for f in _walk(REPO / repo_rel):
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if ABS.search(line):
                    hits.append(f"{f.relative_to(REPO)}:{n}: {line.strip()[:90]}")
    assert hits == [], hits


# --- T5: the rosters launcher --------------------------------------------------------------------
def _load_rosters_launcher():
    """Import `pipeline/rosters/run_rosters.py` as a module, for the same reason as the other two:
    a substring search over a launcher's source is satisfied by its own docstring (T2 final R5)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sar_run_rosters", REPO / "pipeline/rosters/run_rosters.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_rosters_launcher_registers_every_ported_script_and_gates_the_api_one():
    rs = _load_rosters_launcher()
    assert set(rs.STAGES) == {"merge", "variants", "incfel", "final", "fnfix",
                              "econ-audit", "econ-merge"}, sorted(rs.STAGES)

    # 70_prep_fnfix_inputs.py walks the live OpenAlex API. It has no --execute, by design.
    assert rs.STAGES["fnfix"].gate, (
        "the fn-fix stage's gate is gone. Without it `run_rosters.py fnfix` would call the live "
        "OpenAlex API and rewrite the run configs with today's data.")
    for name in ("merge", "variants", "final"):
        assert rs.STAGES[name].gate is None, f"{name} must run by default"

    for name, stage in sorted(rs.STAGES.items()):
        assert (REPO / "pipeline/rosters" / stage.script).is_file(), f"{name}: {stage.script}"
        if stage.gate:
            continue
        assert stage.links or stage.no_links_reason, (
            f"{name}: a stage that runs must declare the inputs its mirror needs, or say in "
            f"no_links_reason why it needs none")
        if not stage.links:
            assert len(stage.no_links_reason or "") > 40, f"{name}: no_links_reason needs substance"
        assert stage.outputs, f"{name}: a stage that runs must declare what it produces"
        # every link's destination must sit INSIDE the mirror; `..` would escape the scratch tree
        for dest_rel, src_rel in stage.links:
            assert not dest_rel.startswith("/") and ".." not in dest_rel.split("/"), (name, dest_rel)
            assert not src_rel.startswith("/") and ".." not in src_rel.split("/"), (name, src_rel)

    # only 00b derives an output location from __file__, so only 00b may be relocated: relocating a
    # script that does not need it would move the reviewed copy out of the comparison for nothing
    relocated = {n for n, s in rs.STAGES.items() if s.relocate}
    assert relocated == {"variants"}, relocated
    src = (REPO / "pipeline/rosters" / rs.STAGES["variants"].script).read_text(encoding="utf-8")
    assert "os.path.abspath(__file__)" in src, (
        "the variants stage is relocated but its script no longer derives an output from __file__")

    assert rs.unregistered_scripts() == [], rs.unregistered_scripts()

    # a stage whose script is RECOVERED must say so, and only those may
    # `also` scripts count too: `econ-merge`'s reject_cause enrichment is recovered as well, and its
    # stage's `recovered` string names both ops (milestone review BLOCKER).
    declared = {f"pipeline/rosters/{s.script}" for s in rs.STAGES.values() if s.recovered}
    declared |= {f"pipeline/rosters/{e}" for s in rs.STAGES.values() if s.recovered for e in s.also}
    mine = {r for r in RECOVERED if r.startswith("pipeline/rosters/")}
    assert declared == mine, {"launcher": sorted(declared), "ledger": sorted(mine)}


def test_the_rosters_launcher_names_no_machine_specific_path():
    assert not ABS.search((REPO / "pipeline/rosters/run_rosters.py").read_text(encoding="utf-8"))


def test_the_roster_scripts_have_no_write_target_the_staging_mirror_does_not_cover():
    """The premise the whole staging design rests on, asserted on the ported sources: each roster
    script resolves exactly ONE root, and it is the one `staged_run_dir` returns. A second absolute
    or `__file__`-derived root would write somewhere the mirror does not reach."""
    for rel in ("pipeline/rosters/multidisc_roster_econ_grade_2026-08-09/verify/"
                "merge_chemmath_verified_v2.py",
                "pipeline/rosters/multidisc_gold_2026-08-10/code/00b_prep_roster_variants.py",
                "pipeline/rosters/multidisc_gold_2026-08-10/code/00c_prep_final_population.py"):
        body = (REPO / rel).read_text(encoding="utf-8")
        for blk in PREAMBLE_BLOCKS:
            body = body.replace(blk, "")
        assert body.count("_sar_staged(") == 1, f"{rel}: {body.count('_sar_staged(')} staged roots"
        assert not ABS.search(body), rel


# --- T6: the stars launcher -----------------------------------------------------------------------
def _load_stars_launcher():
    """Import `pipeline/stars/run_stars.py` as a module. Same reason as the other three launchers:
    T2 final review R5 showed a substring search over a launcher's source is satisfied by its own
    docstring, so every claim below is asserted on the imported objects."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sar_run_stars", REPO / "pipeline/stars/run_stars.py")
    mod = importlib.util.module_from_spec(spec)
    # registered BEFORE exec: `Stage` is a dataclass in a module using `from __future__ import
    # annotations`, so dataclasses resolves its string annotations through sys.modules[__module__]
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_stars_launcher_registers_every_ported_script_and_gates_the_expensive_ones():
    st = _load_stars_launcher()
    assert set(st.STAGES) == {"candidates", "events-chemmath", "events-econ", "u4aug", "restake",
                              "suspects", "prescreen", "prefetch"}, sorted(st.STAGES)

    # `u4aug` is the acceptance rerun and must stay ON; everything else costs minutes or calls the
    # live OpenAlex API, and a gate that quietly disappeared is exactly the T4 MAJOR-1 shape.
    for name in ("candidates", "events-chemmath", "events-econ", "u4aug"):
        assert st.STAGES[name].gate is None, f"{name} is cheap and must run by default"

    # every RECOVERED stage must say so, and only those may (the ledger is the authority)
    declared = {f"pipeline/stars/{s.script}" for s in st.STAGES.values() if s.recovered}
    declared |= {f"pipeline/stars/{a}" for s in st.STAGES.values() if s.recovered for a in s.also}
    declared |= {f"pipeline/stars/{k}" for k in st.NOT_RUNNABLE
                 if k.rsplit("/", 1)[1].startswith("00_build_candidates_restake")}
    mine = {r for r in RECOVERED if r.startswith("pipeline/stars/")}
    assert declared == mine, {"launcher": sorted(declared), "ledger": sorted(mine)}
    # a stage that runs with a changed working directory, or writes into a sibling run directory,
    # is exactly the recovered pair - nothing else may quietly acquire either power
    assert {n for n, s in st.STAGES.items() if s.cwd} == {"candidates", "events-chemmath",
                                                         "events-econ"}
    # `also` chains extra ported scripts into one run directory - only the candidate table needs it
    assert {n for n, s in st.STAGES.items() if s.also} == {"candidates"}
    assert {n for n, s in st.STAGES.items() if s.stage_dirs} == {"events-econ"}
    for name in ("restake", "suspects", "prescreen", "prefetch"):
        assert st.STAGES[name].gate and len(st.STAGES[name].gate) > 120, (
            f"{name}: the cost gate is gone or has become a stub. `restake` and `suspects` each rank "
            f"the whole snapshot population over 24 GB of edge tables; `prescreen` and `prefetch` "
            f"call the live API, whose answer today is NOT the 2026-08-15 answer.")

    for name, spec in sorted(st.STAGES.items()):
        assert (REPO / "pipeline/stars" / spec.script).is_file(), f"{name}: {spec.script}"
        for dest_rel, src_rel in spec.links:
            assert not dest_rel.startswith("/") and ".." not in dest_rel.split("/"), (name, dest_rel)
            assert not src_rel.startswith("/") and ".." not in src_rel.split("/"), (name, src_rel)
        if spec.gate is None:
            assert spec.outputs, f"{name}: a stage that runs by default must declare what it produces"

    # a ported script nobody registered would run with no gate and no staged output location
    assert st.unregistered_scripts() == [], st.unregistered_scripts()

    # the scratch root's BASENAME is load-bearing: the ported preamble finds the repo by walking up
    # to a directory named "stars", and $SAR_OUT_ROOT redirects to <root>/<basename>.
    assert st.SCRATCH.name == "stars" and st.SCRATCH.parent == REPO / "output", st.SCRATCH


# --- T7 review MAJOR-2: the frames launcher, asserted the way the other four are -----------------
# Drivers (T2), fwci (T4), rosters (T5) and stars (T6) each carry a coverage block; frames shipped
# without one, and the T7 report claimed an assertion that existed nowhere. That is T2-review-F5
# exactly. These two tests are the stars block ported to this layer.

def _load_frames_launcher():
    """Import `pipeline/frames/run_frames.py` as a module. Same reason as the other four: a
    substring search over a launcher's source is satisfied by its own docstring (T2 final R5), so
    every claim below is asserted on the imported objects."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sar_run_frames",
                                                  REPO / "pipeline/frames/run_frames.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # `Stage` is a dataclass under `from __future__ import
    spec.loader.exec_module(mod)          # annotations`; dataclasses resolves via sys.modules
    return mod


def test_the_frames_launcher_registers_every_ported_script_and_gates_the_ssd_stages():
    fr = _load_frames_launcher()
    assert set(fr.STAGES) == {"afar", "speed", "split", "ledger", "union-gold",
                              "p1-gold", "p2-gold", "p2-econ", "p1-econ"}, sorted(fr.STAGES)

    # the four boot-volume stages are the acceptance proof's cheap half and must stay ON
    for name in ("afar", "speed", "split", "ledger"):
        assert fr.STAGES[name].gate is None, f"{name} needs no data disk and must run by default"
    # the five that touch the data disk must keep a real cost gate (the T4 MAJOR-1 shape)
    for name in ("union-gold", "p1-gold", "p2-gold", "p2-econ", "p1-econ"):
        assert fr.STAGES[name].gate and len(fr.STAGES[name].gate) > 120, (
            f"{name}: the cost gate is gone or has become a stub. Each of these scans 1-2.5 GB of "
            f"U1 derived tables off the data disk and asks DuckDB for 8-10 GB of RAM.")

    # every RECOVERED stage must say so, and only those may - the ledger is the authority
    declared = {f"pipeline/frames/{s.script}" for s in fr.STAGES.values() if s.recovered}
    mine = {r for r in RECOVERED if r.startswith("pipeline/frames/")}
    assert declared == mine, {"launcher": sorted(declared), "ledger": sorted(mine)}
    # both recovered producers ran as `cd <run dir> && python3 - <<EOF`, so their paths are all
    # relative; nothing else may quietly acquire the power to change the working directory
    assert {n for n, s in fr.STAGES.items() if s.cwd} == {"speed", "split"}
    # `also` chains a second ported script into one run directory - only the leftbehind pair needs it
    assert {n for n, s in fr.STAGES.items() if s.also} == {"afar"}
    # hazard H4: GOLDVAR=fnfix, and ONLY for the three gold builders. Without it every gold script
    # succeeds against the wrong variant and writes plausible-looking output.
    assert {n for n, s in fr.STAGES.items() if s.env} == {"union-gold", "p1-gold", "p2-gold"}
    for name in ("union-gold", "p1-gold", "p2-gold"):
        assert fr.STAGES[name].env == (("GOLDVAR", "fnfix"),), fr.STAGES[name].env

    frozen = {f.name for f in (REPO / "data/frames").iterdir() if f.is_file()}
    for name, spec in sorted(fr.STAGES.items()):
        assert (REPO / "pipeline/frames" / spec.script).is_file(), f"{name}: {spec.script}"
        for dest_rel, src_rel in spec.links:
            assert not dest_rel.startswith("/") and ".." not in dest_rel.split("/"), (name, dest_rel)
            assert not src_rel.startswith("/") and ".." not in src_rel.split("/"), (name, src_rel)
        assert spec.outputs, f"{name}: a stage must declare what it produces"
        # cal2026-08-28 T3: `union-gold` rebuilds an INPUT of p1-gold/p2-gold, one rung above the
        # frozen frame set, so it is the one stage allowed an empty `frames` declaration.
        assert spec.frames or name == "union-gold", (
            f"{name}: a frames stage must name the frozen frames it rebuilds")
        for rel in spec.frames:
            assert rel in frozen, f"{name} claims to rebuild {rel}, which is not in data/frames/"

    # a ported script nobody registered would run with no gate and no staged output location
    assert fr.unregistered_scripts() == [], fr.unregistered_scripts()
    # ... and the escape hatch is not a free pass: each entry must exist and carry a real reason
    stage_scripts = {s.script for s in fr.STAGES.values()}
    for rel, why in sorted(fr.NOT_RUNNABLE.items()):
        assert (REPO / "pipeline/frames" / rel).is_file(), rel
        assert len(why.strip()) > 80, f"{rel}: a NOT_RUNNABLE entry needs a real reason"
        assert rel not in stage_scripts, f"{rel} is both a stage and NOT_RUNNABLE"
    # `60_lb_tau.py` is NOT_RUNNABLE as a stage of its own yet IS executed, as `afar`'s second half
    assert "p3_topicpair_2026-08-17/code/60_lb_tau.py" in fr.NOT_RUNNABLE
    assert "p3_topicpair_2026-08-17/code/60_lb_tau.py" in fr.STAGES["afar"].also

    # the scratch root's BASENAME is load-bearing: the ported preamble finds the repo by walking up
    # to a directory named "frames", and $SAR_OUT_ROOT redirects to <root>/<basename>.
    assert fr.SCRATCH.name == "frames" and fr.SCRATCH.parent == REPO / "output", fr.SCRATCH
    assert not ABS.search((REPO / "pipeline/frames/run_frames.py").read_text(encoding="utf-8"))


def test_the_frames_pre_import_claim_is_true_in_the_ported_sources():
    """The launcher claims it must pre-import this repo's U0/U4 modules because the ported builders
    would otherwise import the LEGACY ones and compute the y column with them. That has to be true
    of the ported bytes, not of the docstring: exactly the stages that declare `units=True` are the
    ones whose source inserts the legacy units tree on sys.path."""
    fr = _load_frames_launcher()
    needle = 'sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/'
    declared = {n for n, s in fr.STAGES.items() if s.units or s.unit_modules}
    actual = {n for n, s in fr.STAGES.items()
              if needle in (REPO / "pipeline/frames" / s.script).read_text(encoding="utf-8")}
    assert declared == actual == {"p1-gold", "p1-econ", "union-gold"}, (
        {"declared": declared, "actual": actual})
    for src in fr.UNIT_SRC:
        assert src.is_dir() and src.is_relative_to(REPO / "pipeline/units"), src
    # and the modules it binds are the ones the ported builders import by name — the standing trio
    # plus the union builder's extra three (cal2026-08-28 T3)
    assert fr.STAGES["union-gold"].unit_modules == ("identity.dose", "identity.first_pub",
                                                    "common._redlines")
    for module in ("m5_output/fwci_baseline_build.py", "m5_output/fwci_raw.py",
                   "identity/output_rule.py", "identity/dose.py", "identity/first_pub.py",
                   "common/_redlines.py"):
        assert any((src / module).is_file() for src in fr.UNIT_SRC), module


def test_the_stars_pre_import_claim_is_true_in_the_ported_sources():
    """The launcher claims it must pre-import this repo's ranking machine because the ported scripts
    would otherwise import the LEGACY one. That claim has to be true of the ported bytes, not just
    of the docstring: exactly the stages that declare `screening=True` are the ones whose source
    does `from run_screening import _POOL_SQL`, and the module it points at is inside this repo."""
    st = _load_stars_launcher()
    declared = {n for n, s in st.STAGES.items() if s.screening}
    actual = {n for n, s in st.STAGES.items()
              if "from run_screening import _POOL_SQL" in
              (REPO / "pipeline/stars" / s.script).read_text(encoding="utf-8")}
    assert declared == actual == {"restake", "suspects"}, {"declared": declared, "actual": actual}
    assert st.SCREENING == REPO / "pipeline/stars/multidisc_2026-07-24/code/star_screening", st.SCREENING
    for module in ("run_screening.py", "screening_lib.py"):
        assert (st.SCREENING / module).is_file(), module
    # and the line the pre-import defeats is still there, still naming the legacy tree by way of ROOT
    for name in sorted(actual):
        src = (REPO / "pipeline/stars" / st.STAGES[name].script).read_text(encoding="utf-8")
        assert 'SCREEN = f"{ROOT}/v2_output/multidisc_2026-07-24/code/star_screening"' in src, name
        assert "sys.path.insert(0, SCREEN)" in src, name


def test_the_stars_launcher_declares_every_unrunnable_script_with_a_reason():
    """The other half of the partition. A ported script with no stage is either declared here with a
    real reason, or `unregistered_scripts()` fails - it may not simply sit in the layer."""
    st = _load_stars_launcher()
    staged = {s.script for s in st.STAGES.values()}
    assert set(st.NOT_RUNNABLE) & staged == set(), "a script cannot be both staged and NOT_RUNNABLE"
    assert len(st.NOT_RUNNABLE) == 6, sorted(st.NOT_RUNNABLE)
    for script, why in sorted(st.NOT_RUNNABLE.items()):
        assert (REPO / "pipeline/stars" / script).is_file(), script
        assert len(why.strip()) > 120, f"{script}: a not-runnable declaration needs a real reason"


def test_the_stars_gate_cannot_be_switched_off_by_argument_order(monkeypatch):
    """`rest` is an argparse REMAINDER, so it swallows a trailing `--execute` - which would make the
    documented command `run_stars.py restake --execute` silently keep the gate ON (measured: the
    first run of this launcher did exactly that). Both orders must set the flag."""
    st = _load_stars_launcher()
    seen = []
    monkeypatch.setattr(st, "run", lambda stage, execute, rest: seen.append((stage, execute, rest)) or 0)
    assert st.main(["restake", "--execute"]) == 0
    assert st.main(["--execute", "restake"]) == 0
    assert seen == [("restake", True, []), ("restake", True, [])], seen
    seen.clear()
    assert st.main(["restake"]) == 0
    assert seen == [("restake", False, [])], seen


def test_the_stars_gate_refuses_and_stages_nothing_without_the_flag():
    """Behaviour, not declaration: the process must exit non-zero, print the cost, and create no
    run directory."""
    import subprocess
    staged = REPO / "output/stars/multidisc_gold_2026-08-10"
    before = staged.exists()
    r = subprocess.run([sys.executable, str(REPO / "pipeline/stars/run_stars.py"), "suspects"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "OFF by default" in r.stderr and "24 GB" in r.stderr, r.stderr
    assert staged.exists() == before, "the refused stage staged a run directory anyway"


def test_the_stars_launcher_names_no_machine_specific_path():
    assert not ABS.search((REPO / "pipeline/stars/run_stars.py").read_text(encoding="utf-8"))


def test_the_measured_runtimes_agree_between_the_launcher_and_the_readme():
    """T6 review MINOR-3: the README said `suspects  ~22 min` in two places while the report and the
    rebuild tests said 3.6 min; the measured figure is 3.1-3.6. The README is the file a replicator
    reads first, so the two are now cross-pinned and cannot drift apart again."""
    st = _load_stars_launcher()
    readme = (REPO / "pipeline/stars/README.md").read_text(encoding="utf-8")
    assert "~22 min" not in readme, "the 7x-wrong runtime is back in the README"
    for name in ("restake", "suspects"):
        figure = st.STAGES[name].minutes
        assert figure and figure[0].isdigit(), f"{name}: no measured runtime declared"
        assert f"{figure} min" in readme, (
            f"{name}: the launcher says {figure} min and the README does not say so")


# --- T6 review MAJOR-2 (new), second half: a guard that survives the legacy tree being absent -----
def test_the_ported_layer_is_hash_manifested_and_the_manifest_runs_without_the_legacy_trees():
    """The comparison with the private sources cannot run on a replicator's checkout, so
    `tests/pipeline_ported.sha256` records the bytes of every file under `pipeline/`, and THIS
    test has no skip condition at all.

    It is deliberately weaker than the verbatim proofs: it cannot tell a legitimate edit from a
    smuggled one, and one commit can change a file and regenerate the manifest together. What it
    guarantees is that the change is never invisible — it becomes a diff line, on machines where
    nothing else would have spoken."""
    import subprocess
    r = subprocess.run([sys.executable, str(REPO / "tools/verify_ported.py")],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PORTED_OK" in r.stdout, r.stdout
    # and it really covers the star definition
    recorded = (REPO / "tests/pipeline_ported.sha256").read_text(encoding="utf-8")
    for rel in sorted(PATCHED) + sorted(RECOVERED):
        assert rel in recorded, f"{rel} is not in the ported manifest"
    assert _sha((REPO / "pipeline/stars/multidisc_gold_2026-08-10/code/72_restake_fnfix_stars.py"
                 ).read_bytes()) in recorded


def test_the_ported_manifest_actually_catches_a_changed_ported_file(tmp_path, monkeypatch):
    """Falsifiable, not decorative: perturb one byte of the recorded hash and the checker fails."""
    import subprocess
    manifest = REPO / "tests/pipeline_ported.sha256"
    original = manifest.read_text(encoding="utf-8")
    target = "pipeline/stars/multidisc_gold_2026-08-10/code/72_restake_fnfix_stars.py"
    line = next(ln for ln in original.splitlines() if ln.endswith(target))
    tampered = original.replace(line, ("0" * 64) + "  " + target, 1)
    try:
        manifest.write_text(tampered, encoding="utf-8")
        r = subprocess.run([sys.executable, str(REPO / "tools/verify_ported.py")],
                           cwd=REPO, capture_output=True, text=True)
        assert r.returncode == 1, r.stdout
        assert "PORTED_MANIFEST_STALE" in r.stdout and target in r.stdout, r.stdout
    finally:
        manifest.write_text(original, encoding="utf-8")


# --- T6 final review MINOR-7: a guard may only wrap a RESOLVER ------------------------------------
@pytest.mark.parametrize("rel", sorted(set(PATCHED) | set(RECOVERED)))
def test_every_guard_call_wraps_a_resolver(rel):
    """The third layer, and the one that closes the adjacency leak the final review demonstrated.

    Layer 1 (normalise-and-compare) deletes `_sar_*( … )` wrappers, so wrapping a line that never
    held a path folds straight back to the source. Layer 2 (the hunk sanity rule) is supposed to
    catch that — but its unit is the *hunk*, and `SequenceMatcher` merges adjacent changed lines
    into one. In `00_select_new_events_econ.py` the smuggled line
    `"verdict_source":_sar_rd("human_web_verified_round2_2026-08-15")` sits immediately above the
    `E="<absolute path>"` line, so both landed in ONE `replace` opcode whose source side carried the
    absolute path — and that path excused the smuggle. Moving the preamble to the top of the file
    (done) does not help: the adjacency is between the smuggle and `E=`, not the preamble.

    Per-line excusal is not the answer either — it would break the legitimate multi-line case
    (`R_PKG = pathlib.Path(` / `"<abs>/"` / `"v2_output/…")`), where wrapping touches two lines that
    hold no path themselves. So the rule is local and about the wrapper instead of the diff: a guard
    exists to make a RESOLVED ROOT safe, therefore **every guard call must contain a resolver call
    inside its own span**. `_sar_rd("a string literal")` does not, and neither does T5's
    `_sar_out(f"{BASE}/rejected_persons.csv")`. No legitimate wrapper in this port is affected."""
    text = (REPO / rel).read_text(encoding="utf-8")
    body = text
    for blk in PREAMBLE_BLOCKS:                    # the import block names the guards; skip it
        body = body.replace(blk, "")
    offenders = []
    for guard in GUARD_CALLS:
        start = 0
        while True:
            k = body.find(guard, start)
            if k < 0:
                break
            end = _guard_span(body, k, guard)
            start = k + len(guard)
            inner = body[k + len(guard):end - 1]
            if not any(call in inner for call in RESOLVER_CALLS):
                line = body.count("\n", 0, k) + 1
                offenders.append(f"{rel} (+{line} lines after the preamble): {guard}{inner[:70]}…")
    assert offenders == [], (
        "a path guard wraps an expression that contains no resolver call. A guard's whole purpose "
        "is to make a RESOLVED root safe; wrapping anything else is invisible to normalisation and "
        "can be excused by an adjacent path line in the same diff hunk:\n  " + "\n  ".join(offenders))


def test_the_recovered_relative_path_scripts_are_launcher_only_and_that_is_stated():
    """The residual the write barrier cannot cover, pinned so it stays visible. Five recovered
    scripts hold no absolute path, so they make no resolver call, so `refuse_unstaged_in_place_run()`
    never fires for them: `run_stars.py` (which sets the working directory) is the only supported
    entry point. The verbatim rule forbids adding a guard to a line that never held a path, so this
    is documented rather than closed."""
    relative_only = [rel for rel in sorted(RECOVERED)
                     if RECOVERED[rel][3] == 0 and rel.startswith("pipeline/stars/")
                     and rel not in LOST_INPUTS]
    assert len(relative_only) == 4, relative_only
    for rel in relative_only:
        body = (REPO / rel).read_text(encoding="utf-8")
        assert not ABS.search(body), rel
        assert not any(call in body for call in RESOLVER_CALLS), (
            f"{rel} now resolves a root - the import-time guard CAN attach, so update this test "
            f"and pipeline/stars/README.md")
        # T6 final review, §4: the residual is only acceptable because the failure mode is BOUNDED -
        # every path is relative, so an in-place run writes into the caller's own working directory
        # and can never reach a frozen location by way of a constant. Two things would break that
        # bound, so both are refused: an `os.chdir` (the script could move itself somewhere else)
        # and an `open()` on an absolute path.
        assert "os.chdir" not in body and "chdir(" not in body, (
            f"{rel} changes its own working directory - the 'writes only into your cwd' bound in "
            f"pipeline/stars/README.md no longer holds")
        import re as _re                                                # noqa: PLC0415
        absolute_opens = _re.findall(r"open\(\s*['\"]/", body)
        assert absolute_opens == [], (
            f"{rel} opens an absolute path ({len(absolute_opens)} site(s)) - it is no longer "
            f"purely relative, so update this test and the README's bounded-failure claim")

    # The fifth recovered script in this layer is NOT purely relative and is checked separately:
    # rung 4 opens exactly ONE absolute path, and it is the declared lost/reconstructed input.
    rung4 = ("pipeline/stars/multidisc_gold_2026-08-10/code/"
             "00_build_candidates_restake_econ_u4flagged9.py")
    assert rung4 in RECOVERED and rung4 in LOST_INPUTS, rung4
    body = (REPO / rung4).read_text(encoding="utf-8")
    import re as _re                                                    # noqa: PLC0415
    opens = _re.findall(r"open\(\s*'(/[^']+)'\)", body)
    assert opens and all(o.startswith(LOST_INPUTS[rung4][0]) for o in opens), opens
    assert len(opens) == 1 and opens[0].endswith(".output"), opens
    assert "os.chdir" not in body and "chdir(" not in body, rung4
    readme = (REPO / "pipeline/stars/README.md").read_text(encoding="utf-8")
    for claim in ("cannot attach to them",                 # the residual itself
                  "into your working directory",           # what an in-place run actually does
                  "FileNotFoundError"):                    # …and what it does in a normal one
        assert claim in readme, (
            f"the layer's README no longer states {claim!r} - the residual is only acceptable "
            f"because its failure mode is written down and bounded")
# --- symbolic normalisation - the verbatim proof without the private sources ---------------------
# Normalisation folds each resolver call back to the literal it resolves to HERE; folding one step
# further, from that literal to a fixed TOKEN, gives a form of the file that is the same on every
# machine:
#
#     ported  --_normalise()-->  legacy text (this machine's literals)  --_symbolise()-->  symbolic
#     legacy                                                            --_symbolise()-->  symbolic
#
# Both sides land in the same place, so the sha256 of the symbolic form was recorded once, in the
# author's private repository where the legacy sources (and, for RECOVERED files, the replay of the
# working records) were present, and is checked here. The pins live in
# `tests/pipeline_symbolic.sha256`; `tools/verify_symbolic.py` checks them.

#: machine value -> the token it becomes. Longest value first: `_D` and `_S` are `_SSD` plus a
#: component, and `_T` starts with `_HOME`, so a shorter value must never get to replace first.
SYMBOLS: tuple[tuple[str, str], ...] = tuple(sorted(
    ((_D, "<SAR:DERIVED>"), (_S, "<SAR:SNAPSHOT>"), (_SSD, "<SAR:SSD>"), (_T, "<SAR:THESIS>"),
     (_HOME, "<SAR:HOME>"), (_MOUNT, "<SAR:MOUNT>")),
    key=lambda kv: -len(kv[0])))


def _symbolise(text: str) -> str:
    """This machine's absolute path literals -> fixed tokens. The one machine-dependent step, and
    it is applied to BOTH sides of the proof, so what it produces is machine-independent."""
    for value, token in SYMBOLS:
        text = text.replace(value, token)
    return text


def symbolic_form(rel: str) -> str:
    """The port's `rel`, normalised and then symbolised - what gets hashed into the pin file."""
    return _symbolise(_normalise((REPO / rel).read_text(encoding="utf-8")))


SYMBOLIC_MANIFEST = REPO / "tests" / "pipeline_symbolic.sha256"


def _symbolic_pins() -> dict[str, str]:
    out = {}
    if SYMBOLIC_MANIFEST.is_file():
        for line in SYMBOLIC_MANIFEST.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                sha, rel = line.split("  ", 1)
                out[rel] = sha
    return out


def test_the_symbolic_substitution_values_are_distinct_and_do_not_collide():
    """The one thing that could make the symbolic form wrong rather than merely different: a machine
    value short enough, or generic enough, to match text that is not a path. Checked rather than
    assumed, because on a replicator's machine these values are theirs, not the author's."""
    shallow = [(v, tok) for v, tok in SYMBOLS
               if not v.startswith("/") or len(v) <= 6 or v.count("/") < 2]
    if shallow:
        # A property of THIS MACHINE's configuration, not of the port - the same distinction
        # `_ssd_root_mismatch()` above already draws. Someone pointing `legacy_thesis` at
        # `/nonexistent_legacy` to see what runs without it gets a one-component value, and failing
        # here would read like a broken port. The pins themselves are unaffected and still verify
        # (`tools/verify_symbolic.py` -> SYMBOLIC_OK in exactly that configuration); what cannot be
        # guaranteed is that so shallow a literal only ever appears as a path prefix.
        pytest.skip(
            f"PATH TOO SHALLOW, not a broken port: {shallow!r}. Substituting a value with fewer "
            f"than two components could match text that is not a path, so this collision check "
            f"cannot run against it. Point the roots in config/paths.yaml at real locations to "
            f"exercise it; the symbolic pins verify either way.")
    tokens = [t for _v, t in SYMBOLS]
    assert len(set(tokens)) == len(tokens), tokens
    # the tokens must not already occur in anything they will be applied to
    for rel in sorted(set(PATCHED) | set(RECOVERED)):
        text = (REPO / rel).read_text(encoding="utf-8")
        for token in tokens:
            assert token not in text, f"{rel} already contains {token}"


@pytest.mark.parametrize("rel", sorted(set(PATCHED) | set(RECOVERED)))
def test_patched_file_matches_its_pinned_symbolic_form(rel):
    """THE invariant, on a machine with no legacy tree. Undo the port's path substitutions, fold
    this machine's literals to fixed tokens, and the result must be what was recorded when the
    legacy tree WAS present. Anything the port changed that is not path resolution survives both
    steps and moves the hash.

    This is the same proof `test_patched_file_normalises_back_to_its_legacy_source` makes; the only
    difference is what it compares against, and that is exactly the difference that decides whether
    a replicator gets a verbatim layer or 40 skips."""
    pins = _symbolic_pins()
    assert rel in pins, (
        f"{rel} has no symbolic pin. Pins are minted against the private sources, so a changed "
        f"port needs a new pin from the author's private repository.")
    got = hashlib.sha256(symbolic_form(rel).encode("utf-8")).hexdigest()
    assert got == pins[rel], (
        f"{rel}: the normalised, symbolised form is not the one that was recorded against the "
        f"legacy source.\n  recorded {pins[rel]}\n  actual   {got}\n"
        f"Either the port changed something that is not path resolution, or the pin is stale - and "
        f"only the comparison with the private sources can tell you which.")


def test_the_symbolic_pin_file_covers_exactly_the_patched_and_recovered_sets():
    pins = set(_symbolic_pins())
    want = set(PATCHED) | set(RECOVERED)
    assert pins == want, {"unpinned": sorted(want - pins), "stale": sorted(pins - want)}




def test_the_symbolic_pin_is_falsifiable_without_the_legacy_tree():
    """The proof only means something if it can fail. Three mutations of a real ported file, applied
    in memory and never to the tree, each of which the byte manifest would also catch but which
    NOTHING would have caught as "the port changed something that is not path resolution" on a
    machine with no legacy source:

    1. a semantic edit (a threshold moved) - the class the T6 review demonstrated with
       `and aage >= 2` inside `72_restake_fnfix_stars.py`;
    2. a bare guard wrapper around a line that never held a path - normalisation DELETES it, so this
       is the one mutation the symbolic form alone cannot see, and it is named here rather than left
       implied: the sanity layer is what catches it, and this asserts that division of labour;
    3. a path repointed at a different directory - the substitution folds back to a different
       literal, so the symbolic form moves.
    """
    rel = sorted(PATCHED)[0]
    text = (REPO / rel).read_text(encoding="utf-8")
    pin = _symbolic_pins()[rel]
    assert hashlib.sha256(_symbolise(_normalise(text)).encode("utf-8")).hexdigest() == pin

    def _sym(t):
        return hashlib.sha256(_symbolise(_normalise(t)).encode("utf-8")).hexdigest()

    semantic = text.replace("import ", "import os as _smuggled_os  # noqa\nimport ", 1)
    assert semantic != text and _sym(semantic) != pin, "a semantic edit did not move the pin"

    repointed = _symbolise(_normalise(text)).replace("<SAR:DERIVED>", "<SAR:SNAPSHOT>", 1)
    if repointed != _symbolise(_normalise(text)):
        assert hashlib.sha256(repointed.encode("utf-8")).hexdigest() != pin

    # (2), stated as the boundary of this layer rather than as a failure of it
    wrapped = text.replace("import ", "_x = _sar_out(1)\nimport ", 1)
    normalises_away = _normalise(wrapped) == _normalise(text).replace(
        "import ", "_x = 1\nimport ", 1)
    assert normalises_away, (
        "a bare guard wrapper no longer folds away - re-derive which layer catches which form "
        "before trusting either (the same asymmetry test_review_major2_* pins)")


# --- moved to the end of the file: the parametrize below derives its set from PATCHED | RECOVERED,
# and RECOVERED is declared further up only after the roster layer's block comment (MILESTONE REVIEW).
def test_every_guard_using_file_is_pinned_or_explicitly_exempt():
    """MILESTONE REVIEW, port-fidelity MAJOR. The guard-identity pin was a LIST, so it protected
    whatever happened to be on it and said nothing about anything else.

    T6's final review established the policy — a file whose declared destination is a read-and-write
    legacy run directory must use `_sar_staged`, because `_sar_rd` hands the legacy directory back
    and the script writes into it — and pinned the fifteen files that existed then. T7 added five
    frames builders of exactly that shape and nobody extended the pin. The reviewer swapped
    `_sar_staged(` for `_sar_rd(` in one of them and REMOVED the guard outright from another: 274
    verbatim tests passed, `verify_ported.py --write` re-blessed it, `SYMBOLIC_OK`, and a subsequent
    run of the mutated builder **overwrote six frozen artifacts in the read-only legacy tree**.

    So the fix is completeness, not five more entries. The guard-using set is DERIVED from the files
    (`guard_using_files()`), and every member must be either pinned in `GUARDED_DRIVERS` or named in
    `GUARD_PIN_EXEMPT` with the dedicated pin that covers it instead. A future layer cannot be added
    without one or the other, and a file that drops its last guard leaves the derived set and fails
    the stale check below.
    """
    using, declared, exempt = guard_using_files(), set(GUARDED_DRIVERS), set(GUARD_PIN_EXEMPT)
    assert not (declared & exempt), sorted(declared & exempt)
    assert using - declared - exempt == set(), (
        f"guard-using file(s) with no identity pin and no declared exemption: "
        f"{sorted(using - declared - exempt)}. Add the measured multiset to GUARDED_DRIVERS "
        f"(`guard_multiset(rel)` computes it), or declare why a dedicated pin covers it.")
    assert declared - using == set(), (
        f"GUARDED_DRIVERS pins file(s) that no longer use a guard: {sorted(declared - using)}. "
        f"A file that has dropped its last guard is the failure this test exists to see.")
    assert exempt - using == set(), sorted(exempt - using)
    # every exemption must name a real test, and that test must exist
    for rel, why in GUARD_PIN_EXEMPT.items():
        named = re.findall(r"test_[a-z0-9_]+", why)
        assert named, f"{rel}: the exemption names no test"
        source = (REPO / "tests" / "test_verbatim_pipeline.py").read_text(encoding="utf-8")
        for fn in named:
            assert f"def {fn}(" in source, f"{rel}: exemption names {fn}, which does not exist"


#: the stricter half of the old test: EVERY resolver call must sit inside a guard span. It holds for
#: the driver, roster, star and FWCI layers, whose ported code resolves one or two roots. It does NOT
#: hold for the five T7 frames builders, and that is a property of the ported code rather than a
#: choice: `02_clone_chain.py` machine-generated them with three to nine fully-expanded absolute
#: READ paths each, so the port guards the root once (`ROOT = str(_sar_rd(_sar_legacy_thesis()))`)
#: and builds the siblings from the bare resolver. Wrapping each of those would be a hunk that is not
#: path resolution. They are covered by the guard-IDENTITY multiset instead, which is what catches
#: both attacks the milestone reviewer demonstrated (a swap changes the multiset; a removal changes
#: it too), and by `test_no_ported_script_can_be_run_where_it_sits`.
EVERY_RESOLVER_GUARDED_EXEMPT: dict[str, str] = {
    rel: "T7 frames builder: machine-generated with fully-expanded absolute READ paths; the root is "
         "guarded once and the identity multiset is pinned above"
    for rel in sorted(GUARDED_DRIVERS) if rel.startswith("pipeline/frames/")
}


@pytest.mark.parametrize("rel", sorted(guard_using_files() - set(GUARD_PIN_EXEMPT)))
def test_driver_guard_identity_is_pinned(rel):
    """The guard's IDENTITY, over EVERY guard-using file (milestone review, port-fidelity MAJOR).

    `_sar_rd` = "must be readable", `_sar_rw` = "must be writable", `_sar_out`/`_sar_lazyout` =
    "refuse a legacy or frozen destination", `_sar_staged` = "must be a launcher-staged mirror, never
    the legacy directory". Swapping one for another keeps a resolver in the span, normalises away and
    hands the script the LEGACY directory to write into; REMOVING one is worse still. Both were
    demonstrated on unpinned frames builders, and the second overwrote six frozen legacy artifacts.
    The multiset is what sees either.
    """
    text = (REPO / rel).read_text(encoding="utf-8")
    assert "require_readable as _sar_rd" in text and "require_writable as _sar_rw" in text, \
        f"{rel}: the guards are not even imported"
    used = guard_multiset(rel)
    assert used == GUARDED_DRIVERS[rel], (
        f"{rel}: this file uses {used}, the ledger declares {GUARDED_DRIVERS[rel]}. The guard's "
        f"IDENTITY is the safety policy - swapping `_sar_staged(` for `_sar_rd(` keeps a resolver in "
        f"the span, normalises away, and hands the script the LEGACY directory to write into "
        f"(T2-review F3). Change the declaration deliberately, in the same commit.")


@pytest.mark.parametrize("rel", sorted(guard_using_files() - set(GUARD_PIN_EXEMPT)
                                       - set(EVERY_RESOLVER_GUARDED_EXEMPT)))
def test_driver_wires_the_path_guards(rel):
    """`require_readable` / `require_writable` existed since T1 but nothing called them, so a wrong
    ssd_root that happens to EXIST retargeted writes in silence. Every root a driver resolves is now
    wrapped at the point of resolution - import time, before `main()` can open anything - and this
    test greps for it so the wiring cannot quietly disappear."""
    text = (REPO / rel).read_text(encoding="utf-8")
    body = text                                     # the import block names the resolvers; skip it
    for _blk in PREAMBLE_BLOCKS:                    # (T4: whichever block this file carries)
        body = body.replace(_blk, "")
    spans = _guarded_spans(body)
    unguarded = []
    for call in RESOLVER_CALLS:
        start = 0
        while True:
            k = body.find(call, start)
            if k < 0:
                break
            start = k + len(call)
            if not any(a < k and start <= b for a, b in spans):
                line = body.count("\n", 0, k) + 1
                unguarded.append(f"{rel} (+{line} lines after the preamble): {call}")
    assert unguarded == [], (
        "driver resolves a root outside every guard call - a wrong or read-only root would be used "
        "instead of stopping:\n  " + "\n  ".join(unguarded))
