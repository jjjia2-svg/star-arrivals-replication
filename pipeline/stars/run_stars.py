#!/usr/bin/env python3
"""The entry point for the ported star-screening and event-gate scripts — repo-authored.

This is the layer that decides the paper's treatment: who counts as a star, and which arrivals
count as events. The gate definitions it runs are documented, with their source lines, in
`pipeline/stars/README.md`.

Why a launcher, and why this shape. Every ported script here computes its output directory from its
own file (`BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`), a line that holds
no absolute path and therefore may not be touched under M3's verbatim rule — the same situation
`pipeline/fwci/run_fwci.py` was written for. So this launcher moves the FILE, not the constant: it
materialises a run directory under the repo's git-ignored `output/` scratch tree, hard-links the
ported script into `<run dir>/code/` (byte-identity asserted, not assumed), links the inputs the
stage reads relative to `BASE`, and runs THAT. The script then computes exactly the destinations it
always did, one level below a location `output_target()` approved, and not one ported byte differs.

Two stages additionally need the ranking machine, `star_screening/{run_screening,screening_lib}.py`.
The legacy scripts reach it with `sys.path.insert(0, f"{ROOT}/v2_output/.../star_screening")` and
`from run_screening import _POOL_SQL` — and `ROOT` resolves to the READ-ONLY legacy tree, because
that is where the roster parquets and the 79-event ledger they also read still live. Left alone,
that line would import the LEGACY ranking machine into a repo run. So this launcher pre-imports the
repo's copies under those exact module names before the script starts: `sys.modules` already holds
them, the `sys.path.insert` becomes inert, and the SQL that runs is the SQL this repository ships.
The two copies are byte-identical anyway — `tests/test_verbatim_pipeline.py` proves it — so this
changes which file is read, never what it says. The run record prints the `__file__` of each.

    python3 pipeline/stars/run_stars.py --list
    python3 pipeline/stars/run_stars.py u4aug                # seconds; the M3 acceptance rerun
    python3 pipeline/stars/run_stars.py restake --execute    # minutes, needs the data disk
    python3 pipeline/stars/run_stars.py suspects --execute   # ~20 minutes, needs the data disk

`$SAR_OUT_ROOT` works the same way it does for `run_fwci.py`: it moves the scratch root, is itself
judged by the write barrier, and is single-use. Without it the scratch root is `<repo>/output/stars`,
which this launcher CLEARS before staging.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import pathlib
import json
import runpy
import shutil
import sys
import time
from dataclasses import dataclass, field

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
from pipeline.lib.paths import (OUT_ROOT_ENV, STAGE_ROOT_ENV, staged_run,  # noqa: E402
                                PathUnresolved, legacy_thesis, output_target)

STARS_DIR = pathlib.Path(__file__).resolve().parent
#: the scratch root. Its BASENAME must stay "stars": the ported preamble finds the repo by walking
#: up to the directory of that name, and `$SAR_OUT_ROOT` redirects to `<root>/<basename>`.
SCRATCH = REPO / "output" / "stars"
#: where the repo's copy of the ranking machine lives, for the pre-import described above
SCREENING = STARS_DIR / "multidisc_2026-07-24" / "code" / "star_screening"


@dataclass(frozen=True)
class Stage:
    script: str                                   #: ported script, relative to this directory
    outputs: tuple[str, ...]                      #: produced files, relative to the run directory
    links: tuple[tuple[str, str], ...] = ()       #: (dest in run dir, source under v2_output/)
    gate: str | None = None                       #: cost text; a gated stage needs --execute
    screening: bool = False                       #: pre-import the repo's ranking machine
    minutes: str = ""                             #: measured runtime in minutes, cross-pinned to
    #:                                            #: README.md by a test so the two cannot drift
    cwd: bool = False                             #: run with the working directory set to the run dir
    stage_dirs: tuple[str, ...] = ()              #: sibling run directories to materialise + export
    recovered: bool = False                       #: replayed from recorded command history, not copied from a file
    also: tuple[str, ...] = ()                    #: further ported scripts run, in order, after it
    outputs_extra: tuple[str, ...] = ()           #: further files the chain writes, reported too
    payload: tuple[str, str] | None = None        #: (frozen payload file in data/stage_payloads/,
    #:                                            #: ISO timestamp of the original record) of a
    #:                                            #: deleted agent task output this chain reads


#: Every ported script in this layer is either a runnable stage below or declared in NOT_RUNNABLE.
#: Nothing may be neither: `unregistered_scripts()` is asserted empty by the test suite.
STAGES: dict[str, Stage] = {
    # --- the event-selection rung (T6 review BLOCKER-1) -----------------------------------------
    # Neither of these was ever a file: both ran once as a heredoc inside a shell call, and both were
    # replayed out of the author's recorded command history. They are
    # the last gate between "human-confirmed candidate" and "event", so the chain had a hole exactly
    # where the treatment is decided. Both run with the working directory set to the staged gold run
    # directory, because that is where they ran (`cd "<gold>" && python3 - <<EOF`) and every path
    # inside them but one is relative to it.
    "candidates": Stage(
        # The rung ABOVE the selectors, and the file that carries `in_window` — also never a file.
        # Three heredocs, chained in this order in one run directory: chemistry appends to nothing,
        # math-stats appends to chemistry's output, econ appends to that. The FOURTH heredoc
        # (16:02:54.597Z), which appends the last 5 econ rows, is ported but NOT_RUNNABLE: it reads
        # an agent task output from a deleted temporary directory.
        script="multidisc_gold_2026-08-10/code/00_build_candidates_restake_chem.py",
        also=("multidisc_gold_2026-08-10/code/00_build_candidates_restake_math.py",
              "multidisc_gold_2026-08-10/code/00_build_candidates_restake_econ.py",
              "multidisc_gold_2026-08-10/code/00_build_candidates_restake_econ_u4flagged9.py"),
        # T6 final review REOPEN-3. Rung 4 reads four verdicts from an agent task output in a
        # temporary directory the OS reclaimed, which T6 first registered as a lost input. The FILE is
        # gone; its CONTENT is not - the completion record carried the whole envelope inline, it is
        # frozen in data/stage_payloads/, and reconstructing it makes the rung run and the
        # frozen 67-row table rebuild byte for byte. Parsed as DATA, never executed.
        payload=("u4_star_events.json", "2026-08-15T13:09:42.244Z"),
        outputs=("data/fnfix_candidates_restake.csv",),
        links=tuple(
            (f"data/{n}", f"multidisc_gold_2026-08-10/data/{n}") for n in (
                "poach_fn_recheck_chemistry_2026-08-15.csv", "poach_fn_CHECK_chemistry.csv",
                "poach_fn_recheck_math_stats_2026-08-15.csv", "poach_fn_CHECK_math_stats.csv",
                "poach_fn_recheck_econ_2026-08-15.csv", "poach_fn_CHECK_econ.csv")),
        outputs_extra=("data/poach_fn_recheck_econ_U4flagged9_2026-08-16.csv",),
        cwd=True,
        recovered=True,
        minutes="0.01",
    ),
    "events-chemmath": Stage(
        script="multidisc_gold_2026-08-10/code/00_select_new_events_chemmath.py",
        outputs=("data/fnfix_new_events.csv", "data/fnfix_new_events_wide_extra.csv"),
        links=(("data/fnfix_candidates_restake.csv",
                "multidisc_gold_2026-08-10/data/fnfix_candidates_restake.csv"),
               ("data/fnfix_restake_2026-08-15.csv",
                "multidisc_gold_2026-08-10/data/fnfix_restake_2026-08-15.csv"),
               ("data/poach_fn_recheck_chemistry_2026-08-15.csv",
                "multidisc_gold_2026-08-10/data/poach_fn_recheck_chemistry_2026-08-15.csv"),
               ("data/poach_fn_recheck_math_stats_2026-08-15.csv",
                "multidisc_gold_2026-08-10/data/poach_fn_recheck_math_stats_2026-08-15.csv")),
        cwd=True,
        recovered=True,
        minutes="0.01",
    ),
    "events-econ": Stage(
        script="multidisc_gold_2026-08-10/code/00_select_new_events_econ.py",
        outputs=("../econ_fnfix_2026-08-15/data/new_events_econ.csv",),
        links=(("data/fnfix_candidates_restake.csv",
                "multidisc_gold_2026-08-10/data/fnfix_candidates_restake.csv"),
               ("data/fnfix_restake_2026-08-15.csv",
                "multidisc_gold_2026-08-10/data/fnfix_restake_2026-08-15.csv"),
               ("data/poach_fn_recheck_econ_2026-08-15.csv",
                "multidisc_gold_2026-08-10/data/poach_fn_recheck_econ_2026-08-15.csv"),
               ("data/poach_fn_recheck_econ_U4flagged9_2026-08-16.csv",
                "multidisc_gold_2026-08-10/data/poach_fn_recheck_econ_U4flagged9_2026-08-16.csv")),
        cwd=True,
        recovered=True,
        # its ONE absolute constant is the econ_fnfix run directory it writes into, so that
        # directory is staged as a sibling and handed over through $SAR_STAGE_ROOT
        stage_dirs=("econ_fnfix_2026-08-15/data",),
        minutes="0.01",
    ),
    "u4aug": Stage(
        script="econ_fnfix_2026-08-15/code/00_make_u4_aug.py",
        outputs=("u4_aug/events/data.parquet", "u4_aug/star_set/star_set.parquet",
                 "config/econ_fnfix.json"),
        links=(("data/new_events_econ.csv",
                "econ_fnfix_2026-08-15/data/new_events_econ.csv"),),
        minutes="0.1",
    ),
    "restake": Stage(
        script="multidisc_gold_2026-08-10/code/72_restake_fnfix_stars.py",
        outputs=("data/fnfix_restake_2026-08-15.csv",),
        links=(("data/fnfix_candidates_restake.csv",
                "multidisc_gold_2026-08-10/data/fnfix_candidates_restake.csv"),
               ("verify/fnfix_work_level_calls.csv",
                "multidisc_gold_2026-08-10/verify/fnfix_work_level_calls.csv")),
        gate=("two complete rankings of the whole snapshot population, one before and one after the "
              "per-paper identity drops, at every distinct arrival year of the 67 re-stake "
              "candidates. It reads <derived>/u1_edges_full_2026-07-05 (24 GB of authorship edges "
              "and works) and asks DuckDB for up to 12 GB of RAM. No cloud cost, but the data disk "
              "must be mounted and the machine is busy for MINUTES (see README.md)."),
        screening=True,
        minutes="2.3-2.8",
    ),
    "suspects": Stage(
        script="multidisc_gold_2026-08-10/code/60_poach_gate_false_negatives.py",
        outputs=("data/poach_fn_suspects_econ.csv", "data/poach_fn_suspects_chemistry.csv",
                 "data/poach_fn_suspects_math_stats.csv"),
        links=(("data/events_chemistry_final_2026-08-13.csv",
                "multidisc_gold_2026-08-10/data/events_chemistry_final_2026-08-13.csv"),
               ("data/events_math_stats_final_2026-08-13.csv",
                "multidisc_gold_2026-08-10/data/events_math_stats_final_2026-08-13.csv")),
        gate=("one complete ranking of the whole snapshot population at EVERY arrival year in the "
              "three rosters — thousands of people, not 67 — over the same 24 GB of edge tables. "
              "This is the most expensive stage in the layer (see README.md for the measured "
              "runtime); it needs the data disk and no cloud."),
        screening=True,
        minutes="3.1-3.6",
    ),
    "prescreen": Stage(
        script="multidisc_gold_2026-08-10/code/61_poach_fn_prescreen_v2.py",
        outputs=("data/poach_fn_prescreen_v2_2026-08-15.csv",),
        links=(("data/poach_fn_suspects_econ.csv",
                "multidisc_gold_2026-08-10/data/poach_fn_suspects_econ.csv"),
               ("data/poach_fn_suspects_chemistry.csv",
                "multidisc_gold_2026-08-10/data/poach_fn_suspects_chemistry.csv"),
               ("data/poach_fn_suspects_math_stats.csv",
                "multidisc_gold_2026-08-10/data/poach_fn_suspects_math_stats.csv"),
               ("data/_poach_profile_cache.json",
                "multidisc_gold_2026-08-10/data/_poach_profile_cache.json")),
        gate=("it calls the LIVE OpenAlex API for every suspect not already in "
              "_poach_profile_cache.json, and reads the key out of ~/.zshrc. A fresh call today "
              "returns DIFFERENT data — OpenAlex keeps back-filling current affiliations onto old "
              "works, which is the very defect this gate exists to repair — so a live re-run is not "
              "a reproduction. The 2026-08-15 cache is linked in, so with it present nothing is "
              "fetched; without it the classification would drift."),
        minutes="0.2 (fully cached)",
    ),
    "prefetch": Stage(
        script="multidisc_gold_2026-08-10/code/75_prefetch_star_works.py",
        outputs=(),
        gate=("it calls the LIVE OpenAlex API to cache one star's complete works list, reading the "
              "key out of ~/.zshrc, and takes author ids as command-line arguments. Same drift "
              "argument as prescreen: today's answer is not 2026-08-15's answer."),
        minutes="n/a",
    ),
}

#: ported scripts with NO runnable stage, and why. A script here has been read and judged, not
#: forgotten: the count is pinned and the test suite requires a real reason for each.
NOT_RUNNABLE: dict[str, str] = {
    "multidisc_2026-07-24/code/star_screening/run_screening.py":
        "the ranking machine itself. Two things are true at once: its `_POOL_SQL` and its "
        "`foreign_prescreen` ARE executed by this launcher (the `restake` and `suspects` stages "
        "pre-import this exact file), but its own end-to-end `main()` is not a stage. main() needs "
        "the 2026-07-24 chemistry/math silver roster staged as its run directory's input and writes "
        "its shortlist back into that run directory; its BASE therefore goes through the write "
        "barrier, which refuses the legacy destination. Its outputs from the original run survive "
        "in the legacy tree.",
    "multidisc_2026-07-24/code/star_screening/screening_lib.py":
        "a pure-function module with no IO and no __main__: the signed thresholds, the milojevic "
        "age bins, and the exact-arithmetic three-state star flags. It is imported by "
        "run_screening.py and by the 60/72 stages, so it is exercised, not idle.",
    "multidisc_gold_2026-08-10/code/71_parse_verdicts.py":
        "a parser whose input is a HUMAN round: it takes the JSON a verification workflow returned "
        "for the 192-person two-round check and writes it out as a CSV. The JSON was never a file "
        "in any tree, and re-running the human round is what cannot be reproduced. Its output "
        "ledgers survive; see pipeline/NOT_REPRODUCIBLE.md.",
    "multidisc_gold_2026-08-10/code/73_make_recheck_args.py":
        "builds the argument packet for round 2 out of round 1's verdict CSV, which is itself a "
        "human product (see 71). Runnable in principle, meaningless without the human round.",
    "multidisc_gold_2026-08-10/code/74_parse_recheck.py":
        "the round-2 twin of 71: it takes the JSON the SECOND human verification round returned and "
        "writes poach_fn_recheck_<field>_2026-08-15.csv. Same reason: the input is a human round "
        "whose output was never a file in any tree, and re-running the round is what cannot be "
        "reproduced. Its result ledgers survive; see pipeline/NOT_REPRODUCIBLE.md.",
    "multidisc_gold_2026-08-10/code/76_parse_adjudication.py":
        "parses the per-paper identity adjudication a human/agent round returned into "
        "verify/fnfix_adjudication_<tag>.csv and APPENDS to verify/fnfix_work_level_calls.csv. "
        "Append-only against a frozen 385-row ledger, and its input is the human round.",
}


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def unregistered_scripts() -> list[str]:
    """Ported scripts in this layer that are neither a stage nor declared NOT_RUNNABLE.

    `caliber_2026-08-28/` is excluded: it is not ported code but the repo-authored caliber layer,
    with its own launcher (`run_caliber.py`, declared in `pipeline.lib.paths.LAUNCHERS`) and its
    own sha256 pins in `REPO_AUTHORED` — the partition test covers it there, and registering
    repo-authored files in a ledger of PORTED scripts would misstate what they are.

    `caliber_2026-10/` (2026-09-23) is excluded for the same reason: the October caliber's star
    layer — run_caliber.py / restake_econ11.py / run_cal_estimates.py are declared in `LAUNCHERS`,
    build_calls.py and write_events.py are its data-table steps — all repo-authored, all sha256
    pinned in `REPO_AUTHORED`, none a ported script."""
    known = {s.script for s in STAGES.values()} | {a for s in STAGES.values() for a in s.also} \
        | set(NOT_RUNNABLE)
    me = pathlib.Path(__file__).resolve()
    found = sorted(f.relative_to(STARS_DIR).as_posix() for f in STARS_DIR.rglob("*.py")
                   if f.resolve() != me and "__pycache__" not in f.parts
                   and "caliber_2026-08-28" not in f.parts
                   and "caliber_2026-10" not in f.parts)
    return [f for f in found if f not in known]


def _preimport_screening() -> list[str]:
    """Bind `screening_lib` and `run_screening` to the REPO's copies. See the module docstring."""
    if not SCREENING.is_dir():
        raise PathUnresolved(f"ported ranking machine missing: {SCREENING}")
    if str(SCREENING) not in sys.path:
        sys.path.insert(0, str(SCREENING))
    used = []
    for module in ("screening_lib", "run_screening"):
        loaded = importlib.import_module(module)
        origin = pathlib.Path(getattr(loaded, "__file__", "") or "").resolve()
        if origin.parent != SCREENING:
            raise PathUnresolved(
                f"'{module}' resolved to {origin}, not to this repository's ported copy in "
                f"{SCREENING}. The stage would run the legacy ranking machine.")
        used.append(f"{module} <- {origin.relative_to(REPO)}")
    return used


#: the frozen copy of the one agent-task payload this layer needs, sha256-pinned in
#: `data/MANIFEST.sha256`, parsed as data and never executed. Person-identifying fields were removed
#: for the public package; `author_id`, `verdict` and `arrival_true` are kept.
FROZEN_PAYLOAD = "u4_star_events.json"


def _declared_output(consumer: pathlib.Path) -> str:
    """The one `/…/*.output` path the ported consumer opens, read out of its own source."""
    import re                                                          # noqa: PLC0415
    declared = re.findall(r"open\('(/[^']+\.output)'\)", consumer.read_text(encoding="utf-8"))
    if len(declared) != 1:
        raise PathUnresolved(
            f"{consumer.name} names {len(declared)} task-output files; expected exactly one, and "
            f"the launcher refuses to guess which one to reconstruct.")
    return declared[0]


def _reconstruct_payload(spec: Stage) -> tuple[pathlib.Path, list[pathlib.Path]]:
    """Put the deleted agent task output back where the ported script reads it.

    The destination is NOT written here: it is parsed out of the ported script's own source, so the
    launcher and the port cannot drift apart and no absolute path lives in this file. Returns the
    file written plus the directories created, so `run()` can remove exactly what it made.
    """
    payload_name, _timestamp = spec.payload
    consumer = STARS_DIR / spec.also[-1]
    declared = [_declared_output(consumer)]
    # The payload this stage reads is 6 KB of JSON, FROZEN in `data/stage_payloads/` with its
    # sha256 in `data/MANIFEST.sha256`. Nothing from it is imported or executed: it is parsed as
    # data and written to the path the ported consumer reads.
    frozen = REPO / "data" / "stage_payloads" / payload_name
    if not frozen.is_file():
        raise PathUnresolved(
            f"the frozen task payload ({frozen}) is not on this machine. Rung 4 of the candidate "
            f"chain reads a deleted agent task output; the frozen copy is the only place its "
            f"content survives.")
    payload = json.loads(frozen.read_text(encoding="utf-8"))
    task_id = frozen.name.split(".")[0]
    recorded_path = payload.pop("_recorded_path", None) or _declared_output(consumer)
    print(f"[run_stars] task payload: using the FROZEN copy "
          f"data/stage_payloads/{frozen.name} (sha256-pinned in data/MANIFEST.sha256)")
    dest = pathlib.Path(declared[0])
    if recorded_path != str(dest):
        raise PathUnresolved(
            f"the recorded output file was {recorded_path!r} but the ported script "
            f"reads {str(dest)!r} - refusing to reconstruct a file the consumer does not read.")
    made = [d for d in reversed(dest.parents) if not d.exists()]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"[run_stars] reconstructed task {task_id}'s deleted output from the frozen payload "
          f"({len(payload['result']['results'])} verdicts, parsed as data) -> {dest}")
    return dest, made


def _stage_run_dir(stage: str) -> pathlib.Path:
    """`<scratch>/<legacy run directory name>`, approved by the write barrier."""
    if not os.environ.get(OUT_ROOT_ENV, "").strip():
        if SCRATCH.is_dir() and not SCRATCH.is_symlink() and SCRATCH.parent == REPO / "output":
            shutil.rmtree(SCRATCH)
    scratch = output_target(SCRATCH, f"stars {stage}")
    return scratch / STAGES[stage].script.split("/", 1)[0]


def _link(src: pathlib.Path, dest: pathlib.Path) -> str:
    """Put `src` at `dest` without changing a byte (hard link, copy across filesystems).

    NOTE (T6 review NIT-2): a hard link means the staged script shares an inode with the tracked
    repo file, so a ported script that wrote *beside itself* would modify the tracked source. None
    of them does — every output location is `<run dir>/data`, `<run dir>/u4_aug` or the sibling run
    directory — and `tests/pipeline_ported.sha256` would catch it if one started. A copy would cost
    the `__file__`-identity the FWCI launcher needs, so the link stays and the hazard is written
    down."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    how = "hard link"
    try:
        os.link(src, dest)
    except OSError:
        shutil.copyfile(src, dest)
        how = "copy"
    want, got = _sha(src), _sha(dest)
    if want != got:
        raise SystemExit(f"[run_stars] staged file differs from its source: {want} != {got}")
    return f"{how}, sha256 {got}"


def run(stage: str, execute: bool, rest: list[str]) -> int:
    spec = STAGES[stage]
    if spec.gate and not execute:
        print(f"[run_stars] stage '{stage}' is OFF by default. Cost:\n\n  {spec.gate}\n\n"
              f"  Re-run with --execute if you really want it:\n"
              f"      python3 pipeline/stars/run_stars.py {stage} --execute", file=sys.stderr)
        return 2
    ported = STARS_DIR / spec.script
    if not ported.is_file():
        print(f"[run_stars] ported script missing: {ported}", file=sys.stderr)
        return 2
    try:
        run_dir = _stage_run_dir(stage)
        v2 = legacy_thesis() / "v2_output"
    except PathUnresolved as exc:
        print(f"[run_stars] {exc}", file=sys.stderr)
        return 2

    target = run_dir / "code" / ported.name
    print(f"[run_stars] {stage}: run directory -> {run_dir}")
    # BEFORE anything is created. `run_screening.py`'s own BASE goes through the write barrier, and
    # the barrier's `$SAR_OUT_ROOT` redirect is single-use: it refuses a root that already holds
    # entries. Staging first would create `<root>/stars` and the pre-import would then fail on a
    # root this launcher itself had just filled. Importing first keeps both rules intact.
    if spec.screening:
        for line in _preimport_screening():
            print(f"[run_stars] ranking machine {line}")
    print(f"[run_stars] staged {ported.relative_to(REPO)} ({_link(ported, target)})")
    for dest_rel, src_rel in spec.links:
        src = v2 / src_rel
        if not src.is_file():
            print(f"[run_stars] input missing: {src}", file=sys.stderr)
            return 2
        print(f"[run_stars] input {dest_rel} <- v2_output/{src_rel} "
              f"({_link(src, run_dir / dest_rel)})")
    for rel in spec.outputs:
        (run_dir / rel).parent.mkdir(parents=True, exist_ok=True)
    for rel in spec.stage_dirs:                      # sibling run directories a stage writes into
        (run_dir.parent / rel).mkdir(parents=True, exist_ok=True)
        print(f"[run_stars] staged sibling run directory {run_dir.parent / rel}")

    sys.argv = [str(target), *rest]
    os.environ.setdefault("PYTHONHASHSEED", "0")
    if spec.stage_dirs:
        # `staged_run_dir()` resolves the ported constant to <$SAR_STAGE_ROOT>/<basename>; the
        # scratch root is the only place this launcher is allowed to create output, and the barrier
        # judges it again from inside.
        os.environ[STAGE_ROOT_ENV] = str(run_dir.parent.resolve())
    here = pathlib.Path.cwd()
    payload_file, payload_dirs = (None, [])
    if spec.payload:
        payload_file, payload_dirs = _reconstruct_payload(spec)
    t0 = time.time()
    try:
        if spec.cwd:                                  # the recovered selectors ran `cd <gold> && …`
            os.chdir(run_dir)
            print(f"[run_stars] working directory -> {run_dir}")
        with staged_run(target):                  # in-process staged-run marker (T8)
            runpy.run_path(str(target), run_name="__main__")
        for extra in spec.also:                       # a chain: each step appends to the last one's
            more = STARS_DIR / extra                  # output, in the same run directory
            dest = run_dir / "code" / more.name
            print(f"[run_stars] staged {more.relative_to(REPO)} ({_link(more, dest)})")
            sys.argv = [str(dest), *rest]
            with staged_run(dest):
                runpy.run_path(str(dest), run_name="__main__")
    except PathUnresolved as exc:
        print(f"[run_stars] {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        if int(exc.code or 0):
            return int(exc.code or 0)
    finally:
        os.chdir(here)
        if payload_file is not None and payload_file.exists():
            payload_file.unlink()                  # put the temp area back as we found it
            for d in reversed(payload_dirs):
                try:
                    d.rmdir()
                except OSError:
                    break
        # NIT-5: a staging root left in the environment would silently satisfy `staged_run_dir()`
        # for whatever runs next in this process.
        os.environ.pop(STAGE_ROOT_ENV, None)
    print(f"[run_stars] {stage} finished in {time.time() - t0:.1f} s; outputs:")
    for rel in spec.outputs + spec.outputs_extra:
        f = run_dir / rel
        print(f"    {'OK  ' if f.is_file() else 'MISSING'} {f}"
              + (f"  ({f.stat().st_size:,} B, sha256 {_sha(f)})" if f.is_file() else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run a ported star-screening / event-gate stage in a staged run directory.")
    ap.add_argument("stage", nargs="?", choices=sorted(STAGES), help="which stage to run")
    ap.add_argument("--execute", action="store_true",
                    help="required by the stages that are expensive or call the live API")
    ap.add_argument("--list", action="store_true", help="list the stages, their cost and outputs")
    ap.add_argument("rest", nargs=argparse.REMAINDER, help="arguments passed to the ported script")
    # `rest` is a REMAINDER, so it swallows everything after the stage name - including a trailing
    # `--execute`, which would then silently NOT switch the gate off. Lift the flag out first so the
    # documented form (`run_stars.py restake --execute`) means what it says.
    argv = list(sys.argv[1:] if argv is None else argv)
    execute = "--execute" in argv
    argv = [a for a in argv if a != "--execute"]
    args = ap.parse_args(argv)
    args.execute = execute

    if args.list or not args.stage:
        print(f"star stages (set ${OUT_ROOT_ENV} to move the scratch root):\n")
        for name, spec in STAGES.items():
            print(f"  {name:10s} {spec.script}")
            print("             " + ("** OFF BY DEFAULT - needs --execute: " + spec.gate
                                     if spec.gate else "runs by default")
                  + f"  [measured: {spec.minutes} min]")
            for rel in spec.outputs:
                print(f"             -> <run dir>/{rel}")
            if not spec.outputs:
                print("             -> ** NO OUTPUT REGISTERED")
        print("\n  ported scripts with no runnable stage (read and judged, not forgotten):")
        for script, why in NOT_RUNNABLE.items():
            print(f"    {script}\n        {why[:110]}...")
        if unregistered_scripts():
            print(f"\n  !! ported script(s) neither staged nor declared: {unregistered_scripts()}")
        return 0 if args.stage else 1
    return run(args.stage, args.execute, [a for a in args.rest if a != "--"])


if __name__ == "__main__":
    raise SystemExit(main())
