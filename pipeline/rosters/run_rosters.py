#!/usr/bin/env python3
"""The entry point for the ported roster stages — repo-authored, not part of the verbatim port.

Why a third launcher. The roster scripts have a defect the other two layers do not: **one absolute
constant that is at once the input root and the output root**.

    merge_chemmath_verified_v2.py   BASE = "<v2_output>/multidisc_roster_econ_grade_2026-08-09"
    00b_prep_roster_variants.py     ROOT = "<thesis>";  OUT = dirname(dirname(__file__)) + "/data"
    00c_prep_final_population.py    ROOT = "<thesis>";  OUT = f"{ROOT}/v2_output/.../data/final"

`run_driver.py` resolves a driver's declared output CONSTANT; that cannot work when the same
constant is also where the inputs are. `run_fwci.py` moves the SCRIPT; that cannot work when the
destination comes from an absolute literal rather than from `__file__`. So this launcher does both,
per stage: it builds a **staging mirror** of the legacy run directory with the inputs linked in,
points the ported constant at it through `pipeline.lib.paths.staged_run_dir()`, and — for the one
script whose output really does hang off `__file__` (`00b`) — hard-links the script into that same
mirror so its `dirname(dirname(__file__))/data` lands inside it too.

    python3 pipeline/rosters/run_rosters.py --list
    python3 pipeline/rosters/run_rosters.py merge        # ~10 s, no SSD, no network
    python3 pipeline/rosters/run_rosters.py variants     # ~5 s
    python3 pipeline/rosters/run_rosters.py final        # ~2 s

Nothing is copied into a mirror: inputs are **symlinks** to the read-only legacy files, so a stage
that tries to write over one of its own inputs would be writing through a link into the legacy
tree — and `pipeline/lib/paths.py`'s barrier is not what stops that, the *shape of the mirror* is:
every directory a stage writes into is created as a REAL directory and only its leaves are linked.
That is why the link table below names files, not the directories that hold them, wherever the
stage writes beside them.

`$SAR_OUT_ROOT` moves the scratch root exactly as it does for the other two launchers, and is judged
by the same write barrier. Every stage, `variants` included, runs from a moved root since Task 8:
the ported preamble finds this repository by walking up to a directory named `rosters`, which cannot
name this repo from outside it, but the preamble only APPENDS to `sys.path` and the launcher runs
the script in-process with the repo already imported — so what the anchor has to do is not raise.
`_check_anchor()` checks exactly that (the component exists, and the directory it computes is not a
second checkout that could shadow this one) and prints what it is doing.

The mirrors are rebuilt from scratch on every run (the scratch tree is git-ignored), so a stage is
never contaminated by the previous one's output.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import re
import runpy
import shutil
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
from pipeline.lib.paths import (OUT_ROOT_ENV, STAGE_ROOT_ENV, staged_run,  # noqa: E402
                                PathUnresolved, legacy_thesis, output_target)

ROSTERS_DIR = pathlib.Path(__file__).resolve().parent
#: the scratch root. Its BASENAME is load-bearing for ONE stage — `variants`, the only stage whose
#: script is relocated — because the ported preamble finds this repo by walking up to a directory
#: named "rosters" and taking its GRANDPARENT. `$SAR_OUT_ROOT` keeps the component
#: (`<root>/rosters/<stage>`) but cannot make the grandparent be this repository; T8 decided that is
#: acceptable, because the preamble only appends to `sys.path` and the launcher has already imported
#: the repo in this process. `_check_anchor()` carries that ruling with its two conditions.
SCRATCH = REPO / "output" / "rosters"

#: `<thesis>` and `<thesis>/v2_output` as prefixes for the link table, so no stage spells either out
V2 = "v2_output"
GRADE = f"{V2}/multidisc_roster_econ_grade_2026-08-09"
GOLD = f"{V2}/multidisc_gold_2026-08-10"
ECON = f"{V2}/econ_roster_verify_2026-08-09"


class Stage:
    """One ported roster script, its staging mirror, and what the mirror must hold.

    `mirror` is the path, RELATIVE TO THE LEGACY THESIS ROOT, that the script's own root constant
    names; the mirror is created at `<stage root>/<its basename>` because that is what
    `staged_run_dir()` returns. `links` are `(path inside the mirror, path under the legacy thesis
    root)` pairs. `relocate` hard-links the ported script into the mirror — needed only when the
    script derives an output location from `__file__`.
    """

    def __init__(self, script: str, mirror: str, links, outputs, *,
                 relocate: str | None = None, gate: str | None = None,
                 no_links_reason: str | None = None, recovered: str | None = None,
                 also=(), cwd: bool = False):
        self.script, self.mirror, self.links, self.outputs = script, mirror, tuple(links), tuple(outputs)
        self.relocate, self.gate = relocate, gate
        #: further ported scripts run, in order, after the main one, in the SAME mirror. The one
        #: user is `econ-merge`: the enrichment that adds `reject_cause` was a separate heredoc run
        #: a few seconds after the merge, against the file the merge had just written.
        self.also = tuple(also)
        #: run with the working directory set to the mirror. The enrichment names its file
        #: RELATIVELY (`pd.read_csv("rejected_persons.csv")`), which is why it holds no absolute
        #: path at all and is ported byte-identically.
        self.cwd = cwd
        #: why a runnable stage links nothing into its mirror (it reads only outside it)
        self.no_links_reason = no_links_reason
        #: set when the ported script was RECOVERED from recorded command history rather than copied
        #: from a surviving file — see pipeline/rosters/README.md and tests/test_verbatim_pipeline.py
        self.recovered = recovered


STAGES: dict[str, Stage] = {
    # 1) the chem/math human-verification merge: 61 + 13 + 5 verified batch files and the two match
    #    tables in, the frozen roster_clean_chemmath_verified.parquet and five ledgers out.
    "merge": Stage(
        script="multidisc_roster_econ_grade_2026-08-09/verify/merge_chemmath_verified_v2.py",
        mirror=GRADE,
        links=[
            ("verify/verified", f"{GRADE}/verify/verified"),
            ("verify/batches", f"{GRADE}/verify/batches"),
            ("verify/verified_gapfill", f"{GRADE}/verify/verified_gapfill"),
            ("verify/batches_gapfill", f"{GRADE}/verify/batches_gapfill"),
            ("verify/verified_rematch", f"{GRADE}/verify/verified_rematch"),
            # the frozen snapshot the merge reads to stay idempotent. Without it the script would
            # fall back to reading (and then overwriting) the live rejected list.
            ("verify/rejected_persons_chemmath_prev_2026-08-10.csv",
             f"{GRADE}/verify/rejected_persons_chemmath_prev_2026-08-10.csv"),
            ("match/roster_openalex_match_v2.csv", f"{GRADE}/match/roster_openalex_match_v2.csv"),
            ("match/roster_openalex_match_gapfill.csv",
             f"{GRADE}/match/roster_openalex_match_gapfill.csv"),
        ],
        outputs=[
            "roster_clean_chemmath_verified.parquet",
            "verify/chemmath_roster_verified_all.csv",
            "verify/rejected_persons_chemmath.csv",
            "verify/confirmed_no_openalex_id_chemmath.csv",
            "verify/uncertain_persons_chemmath.csv",
            "verify/merge_stats_v2.json",
        ],
    ),
    # 2) the rank_tag ladder: inc / incamb. NOT the frozen population (that is incfel -> final), but
    #    the only surviving code that states the ladder, and its two variants are checkable.
    "variants": Stage(
        script="multidisc_gold_2026-08-10/code/00b_prep_roster_variants.py",
        mirror="",                                   # the thesis root itself
        links=[
            (f"{GRADE}/roster_clean_chemmath_verified.parquet",
             f"{GRADE}/roster_clean_chemmath_verified.parquet"),
            (f"{GRADE}/collect", f"{GRADE}/collect"),
            (f"{GOLD}/data/events_chemistry_gold_2026-08-10.csv",
             f"{GOLD}/data/events_chemistry_gold_2026-08-10.csv"),
            (f"{GOLD}/data/events_math_stats_gold_2026-08-10.csv",
             f"{GOLD}/data/events_math_stats_gold_2026-08-10.csv"),
        ],
        outputs=[f"{GOLD}/data/inc/roster_gold_chemistry.parquet",
                 f"{GOLD}/data/inc/roster_gold_math_stats.parquet",
                 f"{GOLD}/data/incamb/roster_gold_chemistry.parquet",
                 f"{GOLD}/data/incamb/roster_gold_math_stats.parquet",
                 f"{GOLD}/data/prep_variants_report.json"],
        relocate=f"{GOLD}/code/00b_prep_roster_variants.py",
    ),
    # 2b) the incfel rung — recovered from an inline heredoc, see pipeline/rosters/README.md.
    "incfel": Stage(
        script="multidisc_gold_2026-08-10/code/00b2_prep_incfel_variant.py",
        mirror="",
        links=[
            (f"{GRADE}/roster_clean_chemmath_verified.parquet",
             f"{GRADE}/roster_clean_chemmath_verified.parquet"),
            (f"{GRADE}/verify/chemmath_roster_verified_all.csv",
             f"{GRADE}/verify/chemmath_roster_verified_all.csv"),
            (f"{GRADE}/collect", f"{GRADE}/collect"),
            (f"{GOLD}/config/inc_chemistry.json", f"{GOLD}/config/inc_chemistry.json"),
            (f"{GOLD}/config/inc_math_stats.json", f"{GOLD}/config/inc_math_stats.json"),
        ],
        outputs=[f"{GOLD}/data/incfel/roster_gold_chemistry.parquet",
                 f"{GOLD}/data/incfel/roster_gold_math_stats.parquet",
                 f"{GOLD}/config/incfel_chemistry.json",
                 f"{GOLD}/config/incfel_math_stats.json"],
        recovered="recorded command 2026-08-10T10:38:27.165Z (1 inline heredoc)",
    ),
    # 3) the final population = incfel ∪ the research-centre academic layer. This is the stage whose
    #    output IS the frozen artifact (data/raw_verified/roster_gold_{chemistry,math_stats}.parquet,
    #    by way of 70's copy). Its `incfel` input has no producer — see NOT_REPRODUCIBLE.md.
    "final": Stage(
        script="multidisc_gold_2026-08-10/code/00c_prep_final_population.py",
        mirror="",
        links=[
            (f"{GRADE}/collect", f"{GRADE}/collect"),
            (f"{GOLD}/data/incfel/roster_gold_chemistry.parquet",
             f"{GOLD}/data/incfel/roster_gold_chemistry.parquet"),
            (f"{GOLD}/data/incfel/roster_gold_math_stats.parquet",
             f"{GOLD}/data/incfel/roster_gold_math_stats.parquet"),
            (f"{GOLD}/data/events_chemistry_final_2026-08-13.csv",
             f"{GOLD}/data/events_chemistry_final_2026-08-13.csv"),
            (f"{GOLD}/data/events_math_stats_final_2026-08-13.csv",
             f"{GOLD}/data/events_math_stats_final_2026-08-13.csv"),
        ],
        outputs=[f"{GOLD}/data/final/roster_gold_chemistry.parquet",
                 f"{GOLD}/data/final/roster_gold_math_stats.parquet",
                 f"{GOLD}/data/final/prep_final_report.json"],
    ),
    # 4) the economics roster. Its two producers were never persisted into any tree; they were
    #    RECOVERED from the author's recorded command history by replaying the recorded write and
    #    edit operations in order (see pipeline/rosters/README.md — this is stated as reconstruction,
    #    because that is what it is, and it is trustworthy for exactly one reason: the merge rebuilds
    #    the frozen 920-row parquet byte for byte).
    "econ-audit": Stage(
        script="econ_roster_verify_2026-08-09/code/build_audit.py",
        mirror=ECON,
        links=[],
        no_links_reason=("it reads only OUTSIDE its mirror — the 994-person machine roster in the "
                         "legacy tree and the u0p5 registry panels on the data disk — and writes "
                         "audit/ and batches/ into it"),
        outputs=["audit/econ_roster_evidence_audit.csv", "audit/_summary.json"],
        recovered="recorded command history (1 write + 2 edits)",
    ),
    "econ-merge": Stage(
        script="econ_roster_verify_2026-08-09/code/merge_roster.py",
        mirror=ECON,
        links=[
            ("verified", f"{ECON}/verified"),                       # the 22 human-returned batches
            ("audit", f"{ECON}/audit"),                             # the 994-row machine baseline
        ],
        outputs=["roster_clean_11school_verified.parquet",
                 "econ_roster_verified_all.csv",
                 "rejected_persons.csv"],
        recovered="recorded command history (1 write + 9 edits; the reject_cause enrichment is "
                  "an inline heredoc in the same record, 2026-08-09T12:40:54.559Z)",
        # the enrichment that turns the 12-column rejected_persons.csv into the frozen 13-column
        # one. Registered as a LOST PRODUCER until the milestone review ran the register's own
        # step-6 protocol on it and found it (see pipeline/NOT_REPRODUCIBLE.md).
        also=("econ_roster_verify_2026-08-09/code/add_reject_cause.py",),
        cwd=True,
    ),
    # 5) the fn-fix input builder. Ported for completeness of the chain and NOT RUN: it calls the
    #    live OpenAlex works API for every new star (an unbounded cursor walk), and a fresh call
    #    today returns different data — which is the very defect the fn-fix exists to correct. Its
    #    roster step is a plain shutil.copyfile, so this repo asserts the identity it produced
    #    instead of re-performing it (tests/test_pipeline_rebuild.py).
    "fnfix": Stage(
        script="multidisc_gold_2026-08-10/code/70_prep_fnfix_inputs.py",
        mirror="", links=[], outputs=[],
        gate="it calls the live OpenAlex API (an unbounded cursor walk per new star) and rewrites "
             "the run configs. A fresh call today returns DIFFERENT data — that is the address "
             "back-fill defect the whole fn-fix exists to correct — so re-running it would not "
             "reproduce the 2026-08-15 artifacts, it would replace them with today's. Its roster "
             "step, the only part this layer needs, is `shutil.copyfile(data/final -> data/fnfix)`; "
             "data/final and data/fnfix are sha256-identical and equal to "
             "data/raw_verified/roster_gold_{chemistry,math_stats}.parquet, which "
             "tests/test_pipeline_rebuild.py asserts rather than re-copying. There is no --execute "
             "for this stage.",
    ),
}


#: the system temp root, resolved. The ONLY place this launcher will create a directory outside the
#: scratch tree, and it hard-codes no path of its own — see `_dead_scratch()`.
TMP_ROOT = pathlib.Path("/tmp").resolve()


def _dead_scratch(script: pathlib.Path) -> list[pathlib.Path]:
    """Directories a ported script still writes into that no longer exist.

    `merge_roster.py` ends with four diagnostic writes into the temporary working directory it was
    authored in — a directory under `/private/tmp` the OS has since
    reclaimed. Those four lines carry an absolute path, but it is a path to a location that no
    longer exists, and M3's rule for that (T2, `LOST_INPUTS`) is that it stays VERBATIM: repointing
    it would fabricate provenance. Left alone, the script produces its three real artifacts and then
    dies on the fifth-from-last line. (In the public package the machine- and session-specific part
    of that path is replaced by `/private/tmp/removed-session-directory`.)

    So the launcher re-creates the empty directory before the run and removes what it created after
    it, and the four files are diagnostics, not artifacts (their content is printed to stdout by the
    same script). Nothing is hard-coded here: the paths are read out of the ported script itself,
    and only ones under the system temp root are ever created.
    """
    text = script.read_text(encoding="utf-8")
    out: list[pathlib.Path] = []
    for literal in re.findall(r'"(/[^"\n]+)"', text):
        d = pathlib.Path(literal).parent
        if not d.is_absolute() or d.exists():
            continue
        try:
            d.relative_to(TMP_ROOT)
        except ValueError:
            continue                                  # never create anything outside /tmp
        if d not in out:
            out.append(d)
    return out


def _make_dead_scratch(dirs: list[pathlib.Path]) -> list[pathlib.Path]:
    """Create them, deepest-first bookkeeping so cleanup removes exactly what we made."""
    created = []
    for d in dirs:
        parts = [d] + [q for q in d.parents if not q.exists()]
        for q in sorted({x for x in parts if not x.exists()}, key=lambda x: len(x.parts)):
            q.mkdir()
            created.append(q)
    return created


def _clean_dead_scratch(created: list[pathlib.Path]) -> None:
    for d in sorted(created, key=lambda x: -len(x.parts)):
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.is_file():
                f.unlink()
        try:
            d.rmdir()
        except OSError:
            pass                                      # something else appeared; leave it alone


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def unregistered_scripts() -> list[str]:
    """Ported roster scripts on disk that no stage names. One of those would sit in the layer with
    no staged output location at all; `tests/test_verbatim_pipeline.py` fails on it.

    `cal2026-10/` (2026-09-23) is excluded the way run_stars.py excludes its caliber layers: it
    holds the repo-authored October roster step (merge_network102.py — the D3 fold of the
    2026-09-13 verification of the 102 network-route economists into the verified roster),
    sha256-pinned in `REPO_AUTHORED`, not a ported script — registering it in a ledger of PORTED
    scripts would misstate what it is."""
    registered = {s.script for s in STAGES.values()} | {e for s in STAGES.values() for e in s.also}
    me = pathlib.Path(__file__).resolve()
    found = sorted(f.relative_to(ROSTERS_DIR).as_posix() for f in ROSTERS_DIR.rglob("*.py")
                   if f.resolve() != me and "__pycache__" not in f.parts
                   and "cal2026-10" not in f.parts)
    return [f for f in found if f not in registered]


def _check_anchor(target: pathlib.Path) -> None:
    """The ported preamble walks up to a directory named `rosters` and takes `.parents[1]` as the
    repo. Prove the run will work before `runpy` turns it into an ImportError.

    **The Task 8 decision, recorded (carried from T5's fix wave as "`variants` cannot run from a
    moved root").** Until now this required the grandparent to BE this repository, which is true
    under `<repo>/output/rosters` and cannot be true under a `$SAR_OUT_ROOT` outside the repo — so
    one of six roster stages behaved differently from the other five, and the interim answer was
    "unset $SAR_OUT_ROOT for this stage". That is worse than it looks, because moving the scratch
    root out of the repo is exactly what a replicator on a synced or read-only checkout has to do.

    What the preamble is FOR settles it. Its three lines exist so a ported script run standalone can
    import `pipeline.lib.paths`; they append the computed directory to `sys.path`, they never insert
    it. Under a launcher the import has already succeeded — `run_rosters.py` imported
    `pipeline.lib.paths` before it staged anything, and that module put THIS repository on
    `sys.path` itself — so the append is inert and the anchor only has to not RAISE. Two things must
    hold for that to be safe, and both are checked rather than assumed:

    * an ancestor named `rosters` must exist, or the preamble's `next(...)` raises `StopIteration`
      at import (`$SAR_OUT_ROOT` preserves the component, so it does);
    * the directory the preamble computes must not itself look like a checkout of this repository,
      or a SECOND `pipeline/` package would be reachable and could answer an import this one should.

    When the grandparent is not this repo but both hold, the stage runs and says so.
    """
    anchor = next((p for p in target.parents if p.name == "rosters"), None)
    grandparent = anchor.parents[1] if anchor is not None and len(anchor.parents) > 1 else None
    if grandparent == REPO:
        return                                  # the standalone-correct arrangement
    if anchor is None:
        raise PathUnresolved(
            f"the ported scripts find this repository by walking up to a directory named "
            f"'rosters', and there is no such directory above:\n"
            f"    script {target}\n"
            f"  The preamble's `next(...)` would raise StopIteration at import. ${OUT_ROOT_ENV} "
            f"keeps the 'rosters' component, so this means the scratch root was built by hand.")
    if grandparent is not None and (grandparent / "pipeline" / "lib" / "paths.py").is_file():
        raise PathUnresolved(
            f"the relocated script would compute a DIFFERENT checkout of this repository:\n"
            f"    script {target}\n"
            f"    anchor {anchor}  ->  repo {grandparent}\n"
            f"    this repo {REPO}\n"
            f"  That second tree would be appended to sys.path and could answer an import this one "
            f"should. Choose a ${OUT_ROOT_ENV} that is not inside another copy of the package.")
    if str(REPO) not in sys.path:                # pragma: no cover - this module put it there
        raise PathUnresolved(
            f"{REPO} is not on sys.path, so the relocated script has no way to import "
            f"pipeline.lib.paths once its own anchor stops naming this repository.")
    print(f"[run_rosters] relocated under a moved scratch root: the ported preamble will compute "
          f"{grandparent} as the repo and append it to sys.path, which is inert - {REPO} is already "
          f"there and this launcher runs the script in-process (T8 decision; see _check_anchor).")


def _stage_root(name: str) -> pathlib.Path:
    """`<repo>/output/rosters/<stage>`, approved by the write barrier.

    Only THIS stage's subtree is cleared, never the whole scratch: `merge` and `final` are separate
    commands whose outputs are compared together, so clearing a sibling would delete the evidence of
    the run before it. With `$SAR_OUT_ROOT` set the barrier's ordinary single-use rule applies
    instead — the second run into the same root is refused because the destination is not empty.
    """
    if not os.environ.get(OUT_ROOT_ENV, "").strip():
        default = SCRATCH / name
        if default.is_dir() and not default.is_symlink() and default.parent == SCRATCH:
            shutil.rmtree(default)                     # our own git-ignored scratch
        return output_target(default, f"rosters {name}")
    # redirected: resolve the LAYER root so the "rosters" component survives (T5 review MINOR-2),
    # then hang this stage off it. The barrier judges the layer root, which is what makes the
    # redirect single-use per output root.
    root = output_target(SCRATCH, "rosters")
    root.mkdir(parents=True, exist_ok=True)
    return root / name


def _mirror_path(stage: Stage) -> str:
    """The basename `staged_run_dir()` will hand the ported constant."""
    return pathlib.PurePosixPath(stage.mirror).name if stage.mirror else legacy_thesis().name


def _build_mirror(name: str, stage: Stage, stage_root: pathlib.Path) -> pathlib.Path:
    """Create `<stage root>/<mirror basename>` and link the stage's inputs into it.

    Directories are created REAL and only the named leaves are linked, so a stage cannot write
    through one of its own input links into the read-only legacy tree.
    """
    mirror = stage_root / _mirror_path(stage)
    mirror.mkdir(parents=True)

    thesis = legacy_thesis()
    missing = []
    for dest_rel, src_rel in stage.links:
        src = thesis / src_rel
        if not src.exists():
            missing.append(str(src))
            continue
        dest = mirror / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(src)
    if missing:
        raise PathUnresolved(
            f"[{name}] input(s) not on this machine — the stage reads them from the read-only "
            f"legacy tree:\n    " + "\n    ".join(missing))
    return mirror


def _stage_script(stage: Stage, mirror: pathlib.Path) -> pathlib.Path:
    """Where the ported script will be executed from. `relocate` hard-links it into the mirror (the
    `run_fwci.py` move-the-file pattern) for the one script whose output hangs off `__file__`;
    everything else runs from its ported location, which is the reviewed copy."""
    ported = ROSTERS_DIR / stage.script
    if not ported.is_file():
        raise PathUnresolved(f"ported script missing: {ported}")
    if stage.relocate is None:
        _check_anchor(ported)
        return ported
    dest = mirror / stage.relocate
    _check_anchor(dest)                  # before staging, not after: a refused run leaves no file
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    try:
        os.link(ported, dest)                # a hard link keeps __file__ inside the mirror
    except OSError:
        shutil.copyfile(ported, dest)        # across filesystems
    if _sha(ported) != _sha(dest):
        raise PathUnresolved(f"staged file differs from the ported file: {dest}")
    return dest


def run(name: str, rest: list[str]) -> int:
    stage = STAGES[name]
    if stage.gate:
        print(f"[run_rosters] stage '{name}' does not run in this repository. Why:\n\n"
              f"  {stage.gate}\n", file=sys.stderr)
        return 2
    try:
        stage_root = _stage_root(name)
        mirror = _build_mirror(name, stage, stage_root)
        target = _stage_script(stage, mirror)
    except PathUnresolved as exc:
        print(f"[run_rosters] {exc}", file=sys.stderr)
        return 2

    print(f"[run_rosters] {name}: staging mirror -> {mirror}")
    print(f"[run_rosters] {name}: {len(stage.links)} input link(s); script {target}")
    if stage.recovered:
        print(f"[run_rosters] {name}: this script was RECOVERED from recorded command history "
              f"({stage.recovered}) — see pipeline/rosters/README.md")
    for rel in stage.outputs:                          # DuckDB's COPY does not create directories
        (mirror / rel).parent.mkdir(parents=True, exist_ok=True)
    dead = _make_dead_scratch(_dead_scratch(target))
    for d in dead:
        print(f"[run_rosters] {name}: re-created the ported script's dead scratch dir {d} "
              f"(diagnostics only; removed after the run)")

    sys.argv = [str(target), *rest]
    os.environ.setdefault("PYTHONHASHSEED", "0")
    os.environ[STAGE_ROOT_ENV] = str(stage_root)       # what the ported root constant resolves to
    here = pathlib.Path.cwd()
    t0 = time.time()
    try:
        if stage.cwd:                   # the enrichment names its file relatively; see Stage.cwd
            os.chdir(mirror)
            print(f"[run_rosters] {name}: working directory -> {mirror}")
        with staged_run(target):        # this run is staged, not an in-place run (in-process; T8)
            runpy.run_path(str(target), run_name="__main__")
        for extra in stage.also:
            more = ROSTERS_DIR / extra
            if not more.is_file():
                raise PathUnresolved(f"ported script missing: {more}")
            dest = mirror / pathlib.PurePosixPath(extra).name
            if dest.exists() or dest.is_symlink():
                dest.unlink()
            try:
                os.link(more, dest)
            except OSError:
                shutil.copyfile(more, dest)
            print(f"[run_rosters] {name}: also {more.relative_to(REPO)} -> {dest}")
            sys.argv = [str(dest), *rest]
            with staged_run(dest):
                runpy.run_path(str(dest), run_name="__main__")
    except PathUnresolved as exc:
        print(f"[run_rosters] {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        if int(exc.code or 0):
            _clean_dead_scratch(dead)
            return int(exc.code or 0)
    finally:
        os.chdir(here)
        _clean_dead_scratch(dead)
    print(f"[run_rosters] {name} finished in {time.time() - t0:.1f} s; outputs:")
    ok = True
    for rel in stage.outputs:
        f = mirror / rel
        ok &= f.is_file()
        print(f"    {'OK  ' if f.is_file() else 'MISSING'} {f}"
              + (f"  ({f.stat().st_size:,} B, sha256 {_sha(f)})" if f.is_file() else ""))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run a ported roster stage in a staging mirror the write barrier approved.")
    ap.add_argument("stage", nargs="?", choices=sorted(STAGES), help="which stage to run")
    ap.add_argument("--list", action="store_true", help="list the stages and their outputs")
    ap.add_argument("rest", nargs=argparse.REMAINDER, help="arguments passed to the ported script")
    args = ap.parse_args(argv)

    if args.list or not args.stage:
        relocated = sorted(n for n, s in STAGES.items() if s.relocate)
        print(f"roster stages (set ${OUT_ROOT_ENV} to move the scratch root - EVERY stage, "
              f"including the relocated\n{', '.join(relocated)}, runs from a moved root since T8; "
              f"the scratch root keeps its 'rosters' component and\nthe ported preamble's sys.path "
              f"append is inert under the launcher - see _check_anchor):\n")
        for name, stage in STAGES.items():
            print(f"  {name:9s} {stage.script}")
            print("         " + (f"** DOES NOT RUN: {stage.gate}" if stage.gate
                                 else f"runs by default; mirror <scratch>/{name}/"
                                      f"{_mirror_path(stage)}/"))
            for rel in stage.outputs:
                print(f"         -> {rel}")
        if unregistered_scripts():
            print(f"\n  !! ported script(s) with no stage: {unregistered_scripts()}")
        return 0 if args.stage else 1
    return run(args.stage, [a for a in args.rest if a != "--"])


if __name__ == "__main__":
    raise SystemExit(main())
