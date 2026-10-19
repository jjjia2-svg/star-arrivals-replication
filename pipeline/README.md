# `pipeline/` — the upstream layer (snapshot → frozen frames)

> **Public copy — read this first.** This code needs the 15 GB snapshot extraction (the U1–U3
> tables on the data disk) and the author's read-only working trees, neither of which is in this
> package; the extraction and the human-verification originals are planned for a restricted-access
> archive deposit (no DOI yet). The estimation layer (`analysis/`) does not need any of it. Stages
> that need large data were run on AWS — the U1 snapshot fetch (~17 h, i4i.4xlarge) and the four
> Panel-3 dCDH cells (512 GiB, r6i.16xlarge); their runbooks are in `pipeline/aws/`. For privacy,
> person names in code, comments, tests and documentation are replaced by OpenAlex author ids (or by
> obviously fictional names where a unit test exercises name parsing), archived staff-page fixtures
> were removed (the tests that read them skip), and machine-specific or session-specific paths are
> replaced by neutral placeholders such as `/private/tmp/removed-session-directory`.

The data-collection half of the replication package: units U0–U6, ported from the author's
`multiplex_pipeline/` tree **byte for byte**, with machine-specific paths lifted into
`config/paths.yaml`. The downstream half (`analysis/`, the paper generators) is unaffected by
anything here.

Status: M3 complete (Tasks 1–8). Units, drivers, FWCI, rosters, the star/event gates and the
frames are ported; `run_all.sh` is the entry point; `NOT_REPRODUCIBLE.md` and
`MANIFEST_intermediates.md` are the registers.

**This layer is not self-contained, and no flag makes it so.** It rebuilds the frames from upstream
intermediates the package does not ship. Measured: without the read-only legacy trees 14 of the 15
default stages fail (only `fwci/build` survives); 3 of the 15 additionally need the mounted data
disk. `run_all.sh --list` prints what each stage needs and the run says up front which root is
missing.

## What is here

| Path | What |
|---|---|
| `units/u0…u6/` | the ported pipeline: `src/` + `tests/` per unit, 26,438 LOC of source, 183 test files |
| `contracts/redlines.yaml` | every signed identification threshold; unsigned keys are `null` and raise rather than defaulting |
| `config/econ_dept_phrases/` | the 11 curated department-name phrase lists |
| `lib/paths.py` | path resolution — the only thing the port was allowed to change |
| `lib/r1_config.py` | the R1 run-config loader (`$SAR_R1_CONFIG` = `config/r1/B0.json` or `M.json`): frozen switch registry, signed rulings, STOP codes; repo-authored, callable from the October code with every switch off |
| `run_smoke_m1.py` | U1's entry point (dry-run by default; `--execute` is a ~17 h, 696 GB read) |
| `drivers/` | the end-to-end entry points, recovered from the author's working scripts — `units/` alone cannot be run. Start at `drivers/README.md`: per-driver provenance, what each produced, the gap register, and the list of drivers deliberately not ported |
| `drivers/run_driver.py` | **the documented way to run any driver.** Repo-authored: it reads each driver's own declared output constant, pushes it through the write barrier, and only then `runpy`s the unmodified script |
| `fwci/` | the field baseline the FWCI outcome is divided by: the 37.0-minute full-snapshot scan (**OFF by default**) and the expected-table build M3 actually re-runs and checks. Entry point `fwci/run_fwci.py`; provenance and caliber in `fwci/README.md` |
| `rosters/` | who counts as a colleague. **All four** frozen rosters are re-run here and compared with `tools/content_equal.py`. Two producers are ordinary ports; two were RECOVERED by replaying the author's recorded command history, because they were never files in any tree — that provenance is labelled as reconstruction wherever it appears, and rests on the recovered economics merge rebuilding its frozen parquet byte for byte. Entry point `rosters/run_rosters.py`; provenance in `rosters/README.md` |
| `stars/` | **who counts as a star, and which arrivals count as events** — the layer that defines the treatment. The ranking machine (`star_screening/{run_screening,screening_lib}.py`), the fn-fix gate chain `60 → 61 → 71..76`, the two event-selection steps recovered from the recorded command history (they were never files, and they are what turns a human-confirmed candidate into an event), and `00_make_u4_aug.py`, which is where econ 79 + 38 = 117 happens. Five stages were re-run and compared: both event selections and the 67-row re-stake come back **byte-identical**, and both `u4_aug` parquets content-EQUAL. Entry point `stars/run_stars.py`; the four gate definitions verified line by line, the provenance ruling, and three self-inconsistencies reported-not-fixed are in `stars/README.md` |
| `frames/` | the estimation panels themselves, and the layer's acceptance proof: 21 frozen frames, 19 rebuilt equal. Entry point `frames/run_frames.py`; the acceptance table, the three declared type axes and the one thing that does not match are in `frames/README.md` |
| `run_all.sh` | **the layer's entry point.** Runs the four launchers' default stages in dependency order, gated on exit codes, then the acceptance proof. `--list` explains every stage and why the off-by-default ones are off; `--with-ssd` adds the data-disk stages; `--expensive` adds the 37-minute FWCI scan after printing its cost. The 17-hour U1 fetch is not a stage here at all and no AWS step is reachable under any flag |
| `NOT_REPRODUCIBLE.md` | **the** D2 register (16 entries) — what cannot re-run, why, its hash, and what a replicator can check instead, each check marked `[package]` or `[needs legacy tree]`. It opens with the five entries that were wrong: artifacts declared lost and later recovered |
| `MANIFEST_intermediates.md` | every intermediate artifact between the snapshot and the frames: producer, sha256, and availability (repo / rebuildable / legacy / SSD / gone) |
| `aws/` | the two cloud steps written down — instance type, region, image, command, measured cost and runtime — plus the run logs. `launch_p3_dcdh.sh` and `launch_u1_fetch.sh` print their runbook and exit; neither can launch anything |

**Directory depth is load-bearing.** `common/_redlines.py` finds `contracts/redlines.yaml` by walking
`parents[4]`, and ten more sites anchor on a directory literally named `units`. Moving `contracts/`
or `config/` to the repo root, renaming `units/`, or flattening a level breaks `import common` at
import time and trips the preflight SHA gate.

## Running the tests

```bash
setup/.venv/bin/python -m pytest -q                  # this repo's own tests (pytest.ini pins testpaths = tests)
setup/.venv/bin/python -m pytest -q pipeline/units   # the ported U0-U6 suite: 1,957 tests, ~30 s
```

Both must be green. They are deliberately separate: the ported suite reuses four test-module
basenames across units (and a fifth collides with this repo's `tests/`), so it is collected with
`--import-mode=importlib`. That mode stops putting the test directory on `sys.path`, and three ported
test modules import a sibling by bare name, so `pytest.ini` lists the nine `*/tests` directories under
`pythonpath` — `u6_assemble` first, because it is the only unit doing a bare `import conftest`. No
ported file is edited and no auto-executed file is added to the port.

Two tests skip by default and one is a declared xfail: the live OpenAlex call (`--run-live`), a
reverse-validation contract U0 never produced, and `works_count` in the U6 frame.

## Ported scripts are run through a launcher, never in place

Every ported script derives its output locations from its own `__file__` or from a shared constants
module — lines that hold no absolute path and therefore cannot be changed under the verbatim rule. So
running one where it sits writes into this repository's source tree: before M3 Task 4's review fix, a
plain `python3 pipeline/fwci/…/01_scan_full_snapshot.py` started a 37-minute pass over the snapshot
with no warning and created `{data,logs,partial}/` beside the ported code, holding a second, unhashed
copy of a manifest-pinned artifact.

`pipeline/lib/paths.py::refuse_unstaged_in_place_run()` now refuses that. It attaches to the
`require_readable` / `require_writable` guard the ported path constants already call at import, so it
fires before `main()`, costs the port nothing, and covers the drivers as well as the FWCI scripts.
The repo-authored launchers are exempt and mark the script they stage with an IN-PROCESS marker
(`pipeline/lib/paths.py::staged_run()`), scoped to the block that `runpy`s it. It used to be the
environment variable `$SAR_STAGED_RUN`, which the refusal message itself named — so the documented
way past the guard was to export the variable the error handed you. Exporting it now does nothing.

    setup/.venv/bin/python pipeline/drivers/run_driver.py --list
    setup/.venv/bin/python pipeline/fwci/run_fwci.py --list
    setup/.venv/bin/python pipeline/rosters/run_rosters.py --list
    setup/.venv/bin/python pipeline/stars/run_stars.py --list
    setup/.venv/bin/python pipeline/frames/run_frames.py --list

Or all of them at once, in dependency order, with the acceptance proof at the end:

    bash pipeline/run_all.sh          # the verifiable subset. --list, --with-ssd, --expensive.

Each solves a different shape of the same problem. `run_driver.py` resolves a driver's declared
output CONSTANT; `run_fwci.py` moves the SCRIPT, for a destination computed from `__file__`;
`run_rosters.py` relocates the whole RUN DIRECTORY, for a constant that is at once the script's
input root and its output root.

`output_target()` separately refuses any destination inside this repository that is not under
`output/` — the one location the repo treats as git-ignored scratch.

## Paths, disks and keys

Nothing here reads a hard-coded location. `pipeline/lib/paths.py` resolves everything from
`config/paths.yaml`:

- `ssd_root` — the data root (the legacy external SSD). Its last component must stay
  `openalex_pipeline`; `derived/` and `snapshot/` hang off it. Override with `$SAR_SSD_ROOT`.
- `legacy_multiplex` — the read-only source tree the port is checked against (tests only).
- `pipeline_root` — this directory.
- `$OPENALEX_API_KEY` — the one environment variable the units read (9 sites). Needed only by
  U0.5 author alignment and the preflight environment gate.

Validation policy — deliberately asymmetric, and measured rather than assumed:

- A **missing or empty key** raises `PathUnresolved` naming the key and the file to edit. Never a
  fallback default.
- **`ssd_root`'s last component must be `openalex_pipeline`**, whether it comes from config or from
  the environment. The ported u1 capacity-gate test asserts the derived root ends with
  `openalex_pipeline/derived/`, so a differently-shaped root would surface as a baffling test
  failure instead of a path error.
- **`$SAR_SSD_ROOT` is checked strictly** — it must exist, be a directory, and be writable. Setting
  it is a deliberate act, so a value pointing nowhere is a typo, and that is exactly the case where
  a ported *write* default would otherwise aim at the wrong directory.
- **A `ssd_root` that disagrees with the legacy bytes skips the value proof instead of failing it.**
  The proof folds each resolver call back to the literal it resolves to *on this machine*, so legacy
  files written for a different disk cannot be proven here. That configuration now reports one
  `PATH MISMATCH, not a broken port: …` skip message rather than fourteen byte-diffs that read like
  a broken port. The real fix — normalising the legacy side to a token as well — SHIPPED in Task 8 as
  `tools/verify_symbolic.py` + `tests/pipeline_symbolic.sha256`: the symbolic proof folds both sides
  to fixed tokens, so it needs neither a matching disk nor the legacy tree, and what remains behind
  the `PATH MISMATCH` marker is only the value proof against the legacy FILES.
- **A config `ssd_root` that does not exist still resolves.** The ported units compute module-level
  defaults from it at import and open nothing; requiring existence makes the whole ported suite
  uncollectable on a machine without the 696 GB disk (measured: 15 collection errors). With the
  disk absent the suite is `1995 passed, 5 skipped, 1 xfailed` — the real-data tests skip through
  their own guards.

**The write barrier — added in the Task 2 fix wave.** A ported driver may name a destination that
must never be written on a replicator's machine: `step4_export_r.py` targets the read-only legacy
thesis tree and truncates with `open(…, "w")`, and the U3 driver targets a *frozen* artifact on the
data disk with `resume=False`. Both were protected by a README sentence, and review demonstrated a
plain `python3 …/step4_export_r.py` replacing four pre-existing destination files, exit 0.

`pipeline/lib/paths.py` now refuses any driver destination that is inside a configured legacy root, or
that already exists and is non-empty. It lives in the resolver, so no driver logic is edited:
`output_target()` raises at import (right for a standalone script) and `deferred_output_target()`
returns a path-shaped object that refuses at the first write (right for a constant in a module three
other drivers import). One ported *unit* is guarded the same way: `roster/run_u0p5.py`, a live CLI
whose write root is the frozen `<derived>/u0p5_roster` — its write root only, because a read guard
raises at import and that is what makes the ported suite uncollectable without the disk.

`$SAR_OUT_ROOT` turns a barred driver back on, writing to `$SAR_OUT_ROOT/<original directory name>` —
and **is itself checked against the barrier**, resolved first so a symlink cannot dodge it. Without
that check, pointing it at the directory the artifact originally lived in silently restored the whole
hazard, and the run block *tells* you to set the variable.

Three properties of that variable, so none of them is a surprise:

- **It must be absolute.** A relative value would resolve against the working directory, so the same
  command would write to different places depending on where it was run from. Rejected with the
  absolute path you probably meant.
- **It is single-use per driver.** After a run, `$SAR_OUT_ROOT/<name>` exists and is non-empty, so
  the *next* run into the same root is refused as "frozen" — the barrier cannot tell your previous
  output from the author's. To re-run, use a fresh root (`SAR_OUT_ROOT=$(mktemp -d)`) or delete the
  driver's subdirectory inside it. This is deliberate: silently overwriting your own last run is how
  a comparison against the frozen artifact gets contaminated.
- **Known limit — TOCTOU.** The check happens when the path is resolved; from then on the
  destination is an ordinary `Path`. A symlink planted at it *after* resolution and *before* the
  write would be followed. That needs an attacker or a concurrent mistake in the same window, and
  closing it properly means re-checking at every write — out of scope here, recorded so it is not
  mistaken for a guarantee.

The one destination the barrier cannot reach from inside the port is `step3_run_u6.py`'s `U6_OUT`: it
is built by a legacy line holding no absolute path, so it is not a path-resolution hunk, and attaching
the barrier to `SSD` instead would break the read anchors that hang off the same root. That is what
`drivers/run_driver.py` is for — it applies `output_target()` from *outside* the port and then runs the
unmodified script, so step3 is mechanically barred with zero ported bytes changed. Run drivers through
it; `drivers/README.md` still states, per driver, exactly what would be overwritten and by what it is
stopped.

**Contract for drivers — wired in Task 2.** Every ported driver resolves its roots through
`require_readable(...)` / `require_writable(...)`, at the path constant itself, which is module
level: the check runs on import, before `main()` can open anything, and it cannot be skipped by
invoking the script directly. `tests/test_verbatim_pipeline.py::test_driver_wires_the_path_guards`
greps every driver and fails if a resolver call appears outside a guard, so the contract is enforced
rather than promised. Measured A/B with `$SAR_SSD_ROOT` pointed at an existing but wrong directory:
unguarded, `common80` imports happily and `step1` would have built its output tree there; guarded,
the import stops with `PathUnresolved: a location the pipeline writes is not on this machine: …`.

> **`run_u0p5` is now guarded too.** T1 left it lenient because guarding a module-level constant
> runs the check at *import*, and requiring the disk at import makes the 1,957-test ported suite
> uncollectable (measured: 15 collection errors). That argument holds for `require_readable`, but not
> for `deferred_output_target`, which never raises at import — so its write root
> (`<derived>/u0p5_roster`, frozen and non-empty) is behind the barrier while its read roots stay
> lenient. The u0p5 suite is unchanged at 310 passed / 1 skipped, and the write now refuses.

The unit tests themselves need neither the SSD nor the key.

## The verbatim rule

`tests/test_verbatim_pipeline.py` proves, by sha256, that **391 of the 421** ported files match their
legacy source byte for byte. The other **30** are listed there with their legacy sha256, the
number of path-resolution preamble blocks they carry, and a reason. Nothing under `pipeline/` is
`ADDED` any more (see below), so 421 is the whole layer minus the repo-authored files, each of which
is declared in `REPO_AUTHORED` (132 of them); fifteen of those sit under `analysis/robustness/` — three in `predate/` (the 2026-08-28 date-shift test), three in `battery_2026-08-29/` (the T1-T4 Panel 1 robustness battery), three in `inference/` (the T5 permutation-inference batch), four in `sensitivity/` (the T6 canon reruns, their 2026-09-10 re-staging on the dose>0 Panel 3 frames, and the ± research-centre check on that same cell) and two in `figure4/` (the R1 N5 save_sample driver and its README). A further **12** files are RECOVERED — replayed from the
recorded command history rather than copied from any tree — and carry the same two proof layers.

> These four numbers are `N_IDENTICAL`, `N_WITH_COUNTERPART`, `N_PATCHED` and `len(RECOVERED)` in
> `tests/test_verbatim_pipeline.py`, and
> `test_t8fix_the_documents_state_the_measured_requirement_rather_than_the_old_claim` asserts this
> paragraph against them. They were two tasks out of date until the milestone review measured them.

For those 29 the guarantee is **normalise-and-compare**, not a shape heuristic. The test undoes
the port mechanically — deletes the declared preamble blocks, folds every resolver call back to the
literal it resolves to on this machine, and expands the documentation placeholders — then requires
the result to be **byte-identical to the legacy file**. Anything the port did that was not one of
those substitutions survives normalisation and shows up as a byte difference, wherever it hides:
inside a triple-quoted SQL string, in a Markdown body, in a swapped dataset directory, or in a
swapped resolver. The substitution rules are generic and shared by every patched file, so the rule
table cannot carry a per-file exception, and the preamble-block count is declared in the ledger so
an extra block cannot be deleted into invisibility.

**Every tracked file under `pipeline/` is accounted for**, not just the ones inside a mapped root:
the layer is partitioned into PORTED (has a legacy counterpart), ADDED (sha-pinned; currently empty)
and REPO_AUTHORED. That closes a hole found in review — `drivers/u3_run` is mapped as a single file,
so a stdlib-shadowing `json.py` dropped beside the U3 driver was invisible to every test while
loading first for the documented invocation. Untracked `.py` files under `pipeline/` fail too, since
`git add` is not what makes a shadow dangerous.

`REPO_AUTHORED` is the escape hatch, so it carries the same locks: every entry is **sha256-pinned**,
the **count is pinned**, an auto-executed basename may not be declared, a `.py` may only sit
**directly** in `lib/`, `frames/` or `drivers/` (never in a driver run directory, which becomes
`sys.path[0]`), and no `.py` anywhere in the layer may be named after a standard-library module.
Re-review showed the un-hardened version re-admitted the same `json.py` shadow with one declared
line and everything green.

The two READMEs are pinned along with the code, on purpose: `drivers/README.md` carries the gap
register and the per-driver overwrite table, and those are precisely the claims that were found to
be false twice during review. Editing a pinned file means updating its pin in the same commit —
`tools/repin.sh` does it mechanically, and `tools/repin.sh --check` reports staleness without
writing.

**The launcher's coverage is asserted on its `DRIVERS` map, not on its text.** An earlier version of
that test was a substring search over a file whose own docstring contained every token it looked
for, so emptying step3's entry and refreshing one pin disabled its only control with everything
green. The test now imports the module and inspects the object; a driver with no registered output
constant must be declared self-guarding *and* actually wrap a destination in the barrier, a driver
script nobody registered fails, and `--list` prints an explicit "NO OUTPUT CONSTANT REGISTERED" row
so an empty entry can never look like a safe one. The launcher refuses such a driver at runtime too.
Coverage extends to destinations declared as module-level constants; a future driver that computes
its destination inside `main()` must guard itself, as the U3 driver does.

`tests/test_paths.py` adds an independent second layer: each of the seventeen rewritten paths —
twelve in `units/`, five in `drivers/` — is pinned against the literal **extracted from the legacy
file at test time**, so a value that still looks like path resolution but points somewhere else fails
there too.

**No file in the port is auto-executed.** `ADDED` is empty, and that is the fix rather than an
accident. It briefly held one `pipeline/units/conftest.py` — the bridge that puts the nine ported
`*/tests` directories on `sys.path` — with content pinning and an exemption ledger around it. Review
showed pinning cannot defend a file that is already exempted: appending a payload and updating its
sha256 is the *same* edit, and a `pytest_runtest_makereport` hook installed via
`globals()["".join([...])]` walked straight past the token blacklist, rewrote a signed redline
threshold and turned every failing report into a pass, with all three suites green. The bridge now
lives in `pytest.ini`'s `pythonpath`, which is configuration rather than code and sits in this repo's
ordinary review surface. The auto-executed machinery stays, with an exemption count pinned at zero,
so a future addition has to be declared twice and is announced on every run.

**The ported READMEs are round-trip artefacts, not guidance.** `units/u0p5_dept_roster/README.md`
and `units/u6_assemble/README.md` name the author's own directories, because normalise-and-compare
requires the ported text to fold back to the legacy bytes exactly. Read this file and
`drivers/README.md` for anything a replicator needs to act on; treat the ported READMEs as historical
record of the original run.

Three placeholder tokens appear in ported documentation, each a single reversible substitution:
`<SAR_DERIVED_ROOT>`, `<SAR_SSD_MOUNT>` and `<SAR_HOME>`. The names are deliberately unlike anything
the upstream prose uses — a first draft used `<derived_root>`, which collided with a real docstring
in legacy `run_u4.py`, and the guard caught it.

A bug found in legacy code is reported, never fixed here.
