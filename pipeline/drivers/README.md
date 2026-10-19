# `pipeline/drivers/` — the end-to-end entry points

> **Since M3 Task 4's review fix, running any of these scripts directly is refused.** Each resolves a
> root through `require_readable`/`require_writable` at import, and
> `pipeline/lib/paths.py::refuse_unstaged_in_place_run()` stops a ported script that was not staged by
> a launcher — so the per-driver table below now has a mechanism behind it for every row, not only the
> rows the write barrier could reach. Use `python3 pipeline/drivers/run_driver.py <driver>`.

`pipeline/units/` holds the pipeline's *code*, but it cannot be run: U3's CLI (`units/u3_panel/run_u3.py`)
argparses and then `raise SystemExit`s, and U4 (`units/u4_output_star/src/run_u4.py`) has no `__main__`
at all. Both were always driven from throwaway scripts in the author's working-scripts directory
(159 files, 21,424 LOC, 270 absolute paths). This directory holds the **six of those scripts that
provenance evidence ties to a shipped artifact**, ported under the same verbatim rule as `units/`.

Everything here is the July 2026 economics-only chain. The thesis's August multi-discipline numbers come
from the `v2_output/` layer, which *imports* `units/` but adds its own orchestration; those builders are
M3 Tasks 4–7, not this directory.

## What is here

| File | Unit it drives | Runtime | Verbatim? |
|---|---|---|---|
| `u3_run/run_u3_rebuild_f123_2026-07-06.py` | U3 panel (two-school, 162 k persons) | ~18 min | patched (3 path constants) |
| `final80_p10_2026-07-22/common80.py` | shared constants for the four steps below | — | patched (2 path constants) |
| `final80_p10_2026-07-22/step1_freeze_ship_80ev.py` | U4 star set + events + colleague pool + `paper_contrib` | 20 s | byte-identical |
| `final80_p10_2026-07-22/step2_run_u5_fast.py` | U5 dose (closure-reduced) | ~2 min | byte-identical |
| `final80_p10_2026-07-22/step3_run_u6.py` | U6 frame assembly + gates | ~30 s | byte-identical |
| `final80_p10_2026-07-22/step4_export_r.py` | R export (4 CSVs) | ~10 s | byte-identical |

Depth is load-bearing, exactly as it is for `units/`. Each script computes its own repo anchor by
counting parents: the final80 files use `_HERE.parents[1]` and the U3 driver uses `parents[2]`, and both
must land on `pipeline/`. That is why they sit one directory deep under `drivers/` with their original
run-dated directory names, and it is why the `sys.path` lines needed no patch at all.

## Provenance — which copy actually produced the surviving artifact

Method, following the M1 `run_p3_tp.R` precedent: mtime ordering against the output, provenance strings
*inside* the frozen output, and — where those are not decisive — a content signature only one candidate
copy can produce. All timestamps below are from `stat` on the author's machine; artifact roots are
`<ssd_root>/derived/…` unless stated.

**The single decisive fact for the whole quartet:** `common80.py` is the **only file in the 159-file
working-scripts directory** that names `u4_star_set_p10_80ev_…`, `u5_ship_11school_p10_80ev_…` or
`u6_ship_11school_p10_80ev_…`, and only the four `final80` step files import it (`final52`'s steps import
`common52`, `final16`'s import `common16`). Nothing else can have produced those three directories.
Everything in the table below is corroboration on top of that. Two rows are corroboration *of the ported
copy's behaviour* rather than discriminators between copies, and say so — `final52` and `final80` differ
only in the `common52`→`common80` import line for step2/step3/step4, so their internal literals are
identical.

| Driver | Evidence | Artifact it produced | Ported? |
|---|---|---|---|
| `final80_p10_2026-07-22/common80.py` (mtime 2026-07-22 16:52:23) | precedes every output below; is the only `common*.py` whose `U4_OUT/U5_OUT/U6_OUT` name the p10/80ev directories | (constants only) | **yes** |
| `step1_freeze_ship_80ev.py` (16:53:12) | `u4_star_set_p10_80ev_2026-07-22/` mtime 16:54:28. `_reports/freeze_ship_52ev_report.json` reports `star_set.n = 258` — reachable **only** through this copy: the sibling `final52_2026-07-21/step1_freeze_ship_52ev.py` has no override for star A5068400819 and would emit 197 + 34 = 231. The same report carries this file's un-updated `"date": "2026-07-21"` / `FREEZE_SHIP_52EV_TARGET_ACTUAL_51` literals, and `events.n = 79` matches this copy's p10 comment | `u4_star_set_p10_80ev_2026-07-22/` (star_set 258 rows, hash `ab14c8ab…`; 79 events; `paper_contrib` 518,543 rows; `_roster_pool`) | **yes** |
| `step2_run_u5_fast.py` (16:53:53) | `u5_ship_11school_p10_80ev_2026-07-22/` mtime 16:56:53; the output directory is named by `common80` alone. Corroboration, **not** a discriminator: `_reports/run_summary_u5.json` carries a `closure_domain_reduction` block whose `equivalence` string is this file's literal — but the identical string is also in `final52/step2` and `final16/step2b`. What was re-executed and matched is the ported file's own `pinned_upstream` quad against the frozen one | `u5_ship_11school_p10_80ev_2026-07-22/` (dose_p01, dose_p05, output) | **yes** |
| `step3_run_u6.py` (16:53:53) | `u6_ship_11school_p10_80ev_2026-07-22/` mtime 16:57:30; the output directory is named by `common80` alone. Re-running the ported copy's config path (stopped before any IO) reproduces `3a0361b09cc856f47530c12ade20ae9d4c0692ca09cc3b3d26d53b4206b31040`, the exact `config_sha` in the frozen `frame/_frozen/manifest_header.json` — that proves the **ported file reproduces the frozen run's configuration identity**, not that `final52`'s copy could not (its `frame_fix_version` / `run_tag` literals are byte-identical) | `u6_ship_11school_p10_80ev_2026-07-22/` (frame p01 49,170 / p05 49,434 rows + gates) | **yes** |
| `step4_export_r.py` (16:53:53) | `v2_output/r_p10_80ev_2026-07-22/data/` holds exactly this script's four outputs at 16:57, under its un-updated `_52ev_2026-07-21` filename literals. Decisive: the ported copy was **re-executed with its write root redirected to a temp directory and reproduced all four files byte for byte** (1.0 s) | `analysis_frame_p01_52ev_2026-07-21.csv`, `analysis_frame_p05_…`, `event_coverage_2026-07-21.csv`, `events_v3_52_2026-07-21.csv` | **yes — but do not run**, see below |
| `u3_run/run_u3_rebuild_f123_2026-07-06.py` (2026-07-06 21:30:54) | see the ruling below | `u3_panel_2026-07-06/` (panel 2,018,410 rows, affil_timeline 9,150,587 rows) | **yes** |
| `u3_run/run_u3_fullsmoke_2026-07-06.py` (20:01:52, sha256 `cd5952f8…`) | superseded first pass — see the ruling below | overwritten | no |

### Ruling: the U3 driver is `run_u3_rebuild_f123`, not `run_u3_fullsmoke`

The two files differ in exactly one token — `resume=True` (fullsmoke) versus `resume=False` (rebuild) —
and both mtimes precede the output directory, so mtime ordering alone does not decide it. Three pieces of
content evidence do, and they agree:

1. **The resume short-circuit excludes `fullsmoke` outright.** `m3_panel/panel.py:217` —
   `if resume and dataset_is_valid(out_dir):` returns `{"status": "skipped"}` **without writing
   anything** when the frozen manifest's `upstream_hashes` and `rule_version` match and the two output
   parquets hash-match. The author's note records that the first pass *completed* (2,018,410 rows,
   18.1 min) and that upstream and `RULE_VERSION` were unchanged, so a `resume=True` re-invocation that
   evening would have skipped and left the files at their 20:5x stamps. Every file in the artifact is
   21:35:06 or later — `_reports/*` 21:35–21:39, `panel/data.parquet` 21:47, `affil_timeline/data.parquet`
   21:48, `_frozen/*` 21:48. Therefore the producing run had `resume=False`, which only
   `run_u3_rebuild_f123` has.
2. **Nothing in the artifact predates the rebuild driver**, and the *directory* mtimes (20:56:51 /
   20:58:05) are the trap: they are the first pass's, while the data files inside them are the
   rebuild's. Provenance work on this tree must read file mtimes, never directory mtimes.
3. **The author's own note** (an internal working note of 2026-07-06, sha256 `a772f79e…`, not
   published) states outright that the real panel was rebuilt with the fixed code at
   `resume=False` via `run_u3_rebuild_f123_2026-07-06.py`, and predicts the panel/affil_timeline sha256s
   would be unchanged (they are: `06322f24…` / `939a9c7c…` in `_frozen/manifest.json`).

Two signals that look decisive but are **not**, and are recorded here so nobody leans on them:
`_reports/u3_null_author_rows_count.csv` (the F2 fix) proves the *unit* code was post-fix, which is true
of both drivers; and `_reports` is cleared on **any** run that gets past the resume early return
(`panel.py:232-236`), not only on `resume=False`.

**This corrects the M3 recon report**, whose driver recommendation named `run_u3_fullsmoke_2026-07-06.py`.
Following the M1 precedent, only the true producer is ported; the superseded copy is recorded here with
its hash and is not shipped.

## Where these outputs end up in the shipped repo

`u4_star_set_p10_80ev_2026-07-22/star_set` is a direct input of
`v2_output/econ_fnfix_2026-08-15/code/04_rebuild_y.py`, the builder of the shipped
`data/frames/p1_frame_econ.csv`. `step4`'s `analysis_frame_p01_52ev_2026-07-21.csv` feeds
`r_p10_80ev_2026-07-22/code/00_build_topicdose_frame.py` → `…_topicdose_…csv` →
`frame_dept_2026-07-31/00_build_frame.py` / `econ_final_2026-08-13/code/00_build_frame_econ920.py` →
the shipped economics frame. So this quartet is an ancestor of a shipped artifact, not a side branch.

`u3_panel_2026-07-06` is **not** in that ancestry — the shipped chain reads the 11-school
`u3_panel_11school_2026-07-16`, which was produced on AWS by a driver that is not on disk (see the gaps
below). The U3 driver is ported because it is the only working U3 entry point that survives, and because
it is the reference invocation for U3's injected-dependency wiring.

## Three declared exceptions

**1. `step4_export_r.py` writes into the read-only legacy tree — do not run it.** Its destination is
`<legacy_thesis>/v2_output/r_p10_80ev_2026-07-22`. The port resolves that through `legacy_thesis()`
rather than silently repointing it, because that is genuinely where the July artifact went; repointing
would fabricate provenance. Re-running the script would overwrite frozen legacy files, so it is
documented-not-run. `tests/test_verbatim_pipeline.py::test_step4_export_destination_is_inside_a_read_only_legacy_tree`
pins the fact.

**2. `common80.DRAFT37_CSV` points at a deleted directory and was left verbatim.** The 65-row combined
star shortlist (`new_stars_COMBINED_p10_2026-07-22.csv`) lived in a temporary `/private/tmp` directory
that no longer exists, so `step1` can never rerun end to end. Resolving that constant anywhere would be a
fabrication; it stays pointed at a non-existent location (in the public package the machine- and
session-specific part of the path is replaced by `/private/tmp/removed-session-directory`) and is declared in `LOST_INPUTS` in the verbatim test. This is plan
deviation D2-ii; the rows it carried survive as frozen data (`u4_star_set_p10_80ev_2026-07-22/star_set`
on the SSD, and the economics star/event tables in `data/raw_verified/`).

**3. The run-lines inside the docstrings are stale.** Several ported docstrings say
`<working scripts>/final52_2026-07-21/step1_freeze_ship_52ev.py` and describe "52 events"; the code is the p10 /
80ev (actually 79) version. That is legacy sloppiness, reported and not fixed — the verbatim rule keeps
algorithm and prose exactly as they were. The correct invocations are below.

## Running them — `run_driver.py` is the entry point

```bash
python3 pipeline/drivers/run_driver.py --list        # every driver and where its output would go
python3 pipeline/drivers/run_driver.py step1
SAR_OUT_ROOT=/some/scratch python3 pipeline/drivers/run_driver.py step4
```

`run_driver.py` is repo-authored (declared and sha-pinned in `tests/test_verbatim_pipeline.py`), not
part of the port. It reads each driver's **own** output constant out of `common80` — it hard-codes no
path and re-implements nothing — pushes it through `output_target()`, and only if that returns does it
hand the **unmodified** script to `runpy`. That is what gives `step3_run_u6.py` a mechanism instead of
a warning: its `U6_OUT` comes from a legacy line holding no absolute path, so the barrier cannot
attach inside the port, but the launcher checks it from outside without changing a ported byte.

The bare scripts still work and remain the historical record of how the run was invoked in July —
they are simply not the entry point. Four of the five refuse on their own (two by the barrier, two by
their own HALT); `step3_run_u6.py` is the one that does not, which is the whole reason the launcher
exists.

`--list` on the author's machine, today:

```
step1   !! BARRED (frozen): <derived>/u4_star_set_p10_80ev_2026-07-22
step2   !! BARRED (frozen): <derived>/u5_ship_11school_p10_80ev_2026-07-22
step3   !! BARRED (frozen): <derived>/u6_ship_11school_p10_80ev_2026-07-22
step4   !! BARRED (legacy): <legacy_thesis>/v2_output/r_p10_80ev_2026-07-22
u3      (declares its own OUT; barred at import by the same helper)
```

Everything is barred because every original destination still exists on this machine. Set
`$SAR_OUT_ROOT` to run any of them into a fresh directory — the driver then writes
`$SAR_OUT_ROOT/<original directory name>` and nothing else. It must be an **absolute** path, it is
checked against the same barrier (so it cannot be pointed back at a legacy or frozen location, symlink
included), and it is **single-use per driver**: after one run that subdirectory exists and is
non-empty, so the next run into the same root is refused as "frozen". Use a fresh root
(`SAR_OUT_ROOT=$(mktemp -d)`) or remove the driver's subdirectory to re-run. `step1` additionally can
never complete: its star shortlist input is gone (D2-ii below).

`--list` marks any driver with no registered output constant as `** NO OUTPUT CONSTANT REGISTERED`,
and the launcher refuses to run one unless it is declared self-guarding — an unchecked driver can
never present as a blank, safe-looking row.

### What each driver would overwrite, and what stops it

The overwrite behaviour is not uniform, so it is stated per driver rather than claimed in general. An
earlier draft of this file said all six refuse to touch an existing output; that was false for three
of them (T2-review F5).

| Driver | If its output already exists | What stops it |
|---|---|---|
| `step1_freeze_ship_80ev.py` | `raise SystemExit("HALT: …")` (the message says the directory already exists and is not empty; only new directories are built) | the driver's own check (legacy behaviour, unmodified) **+** the launcher |
| `step2_run_u5_fast.py` | same HALT on `U5_OUT` | the driver's own check **+** the launcher |
| `step3_run_u6.py` | **would overwrite** — `run_u6.run_all(…, force=True)`, and `force` is exactly what bypasses the ledger's `already_done` check | **the launcher only.** Run bare, it still overwrites — that is why `run_driver.py` is the documented entry point |
| `step4_export_r.py` | **would truncate** — `open(…, "w")`, no existence check at all | the write barrier on `R_PKG` (refuses at the first write, inside the port) **+** the launcher |
| `run_u3_rebuild_f123_2026-07-06.py` | **would rebuild in place** — `build_panel(…, resume=False)` clears `_reports` and rewrites `panel/` and `affil_timeline/`, and its input view still exists | the write barrier on `OUT` (refuses at import) **+** the launcher |
| `common80.py` | not a driver — shared constants | — |

### The write barrier

`pipeline/lib/paths.py` refuses any destination that is inside a configured legacy root, or that
already exists and is non-empty on this machine. It lives in the resolver, not in driver logic, so the
port stays verbatim. `output_target()` raises immediately; `deferred_output_target()` returns a
path-shaped object that refuses at the first write (used where a constant lives in a module three
other drivers import).

**`$SAR_OUT_ROOT` is checked against the same barrier it turns off.** Pointing it at the legacy tree —
or at a symlink to it — is refused, resolved first so the symlink cannot dodge the check. Without that,
the obvious wrong value (the directory the artifact originally lived in) silently restored the whole
hazard, and this README's own run block is what tells you to set the variable (T2 re-review R1).

One ported **unit** is guarded the same way: `units/u0p5_dept_roster/src/roster/run_u0p5.py` is a live
CLI whose write root is the frozen, non-empty `<derived>/u0p5_roster` (37 entries). Only its write root
is behind the barrier — guarding a read root would raise at *import*, and that makes the ported unit suite
(1,957 tests in the public copy) uncollectable without the data disk.

## Drivers deliberately NOT ported, and what each would add

| Legacy working-scripts location | LOC | What it would add | Why not now |
|---|---|---|---|
| `final16_2026-07-20/` (`common16`, `step0_registry_v5`, `step1_freeze_ship_16ev`, `step2`, `step2b`, `step3`, `step4`, `step5`) | ~5,000 | the 16-event anchor run. `step1_freeze_ship_16ev.py` (mtime 16:37) produced `u4_star_set_16ev_2026-07-20/` (`_reports/freeze_ship_16ev_report.json`, 16:37), whose 197 star rows and 16 event rows `step1_freeze_ship_80ev.py` reuses **byte for byte**; `step0_registry_v5.py` produced `registry_v5_2026-07-20`, also an input | one step further up the chain. Its own inputs (`registry_v3`, the 9-school rosters) come from the `u0p5_expand_*` tree below, so porting it alone would not make anything runnable that is not runnable now |
| `final52_2026-07-21/` (5 files) | ~750 | the 51-event intermediate run | **dead branch.** `u4_star_set_52ev_2026-07-21` is read by nothing; `step1_freeze_ship_80ev.py` reuses the 16-event freeze, not this one |
| `u5u6_final_2026-07-18/` (3 files), `review_fixes_2026-07-19/step_u6_rerun_v1p1.py` | ~600 | the 07-18/07-19 U4→U5→U6 chain (`u4_star_set_11school_2026-07-16`, `u5_ship_11school_2026-07-18`, `u6_ship_11school_2026-07-19`) | superseded for U5/U6 by the final80 run. **It does not produce `roster_v4_proj8`** — an earlier draft of this file said it did; see the gap register below |
| `u0p5_expand_{adelaide,anu,deakin,macquarie,melbourne,sydney,uq,uts,uwa}/` (9 dirs) | ~13,000, 200 absolute paths | roster construction for the nine expansion schools → `registry_v3/v4/v5` | out of scope by the plan (Task 1 recommendation 4). None of this logic exists in `units/`; roster construction is currently reproducible as data, not as code. **It does not produce the Adelaide gap-fill parquet** — all nine directories are dated 2026-07-11 and none mentions backfill/gapfill/209plus; see the gap register below |
| `u2_scoping_11school/` (5 files), `e6_verify_2026-07-16/` (5 files) | ~1,100 | the 11-school U2 scoping/resolve and the E6 verification re-runs; produced the `*_2026-07-13` and `*_2026-07-16_verify` vintages | neither vintage is in the shipped ancestry — the chain uses the AWS-produced `_2026-07-16` tables |
| the AWS runners for `u1_full_11school_2026-07-16`, `u2_person_map_11school_2026-07-16`, `u3_panel_11school_2026-07-16` | — | the three tables the whole final80 chain sits on | **not on disk.** A repo-wide grep of the legacy tree finds consumers of those three names but no writer; they were produced on the EC2 relay (an AWS launch directory of 2026-07-16 in the author's working scripts). Registered as a gap; M3 Task 8 documents the AWS side |
| `a16_diag_*`, `f_measure_*`, `wave_*`, `u2_build`, `u3_build`, `u4_build`, `pdf_*` | ~1,900 | diagnostics, measurement scratch and PDF tooling | produced no shipped artifact |

## Inputs with no producer anywhere on disk (the gap register)

Five artifacts that the ported chain **reads** have no builder in any tree. They are not "a skipped
driver would add this" — porting the skipped drivers would not make any of them reproducible.

> **The register is `pipeline/NOT_REPRODUCIBLE.md` (entries 11-13), not this table.** Task 8
> consolidated every scattered entry there so there is one authority per fact. What follows is kept
> as the driver layer's own working note; the first two are also declared in
> `tests/test_verbatim_pipeline.py::NO_PRODUCER_INPUTS`, which is what keeps code and prose in step.

| Artifact | Read by | Evidence that no producer exists | What a replicator can check instead |
|---|---|---|---|
| `<derived>/u5u6_final_2026-07-18_work/roster_v4_proj8/dept_roster_panel_{monash,unsw}.parquet` | `common80.ROSTER_V4_PROJ8` → step1's colleague pool | all eight references to the name across both legacy trees **read** it; `u5u6_final_2026-07-18/step1_freeze_ship_u4.py` writes `u4_star_set_11school_2026-07-16`, not this | it is an 8-column projection of `u0p5_roster/roster_v4_2026-07-16` (both 180 rows; 10 columns → 8, hence "proj8"): check the row count and that the 8 columns are a subset of the 10 |
| `<derived>/u0p5_roster/adelaide_backfill_2007_2021_2026-07-20/dept_roster_panel_adelaide_MERGED_209plus_gapfill.parquet` | `common80.ADELAIDE_MERGED` → the colleague pools of the 5 Adelaide gap events of 79 | nothing in either legacy tree writes it; every `u0p5_expand_adelaide` script is dated 2026-07-11 and none mentions backfill/gapfill/209plus | its own `MANIFEST.json` beside the file documents an ad-hoc Wayback-CDX crawl with hand-applied employment gates; and exactly the 5 `ADELAIDE_GAP_EVENT_IDS` depend on it |
| `<derived>/u1_full_11school_2026-07-16/` | the whole chain | consumers but no writer anywhere; produced on the EC2 relay | the U1 provenance manifest inside it (`resolve_provenance` reads it, and step1's frozen `star_set` header matches) |
| `<derived>/u2_person_map_11school_2026-07-16/` | `common80.PM_DIR` | same | `summary_u2_11school.json` beside it |
| `<derived>/u3_panel_11school_2026-07-16/` | `common80.PANEL_SUB` / `TIMELINE_SUB` | same | `summary_u3_11school.json` + `preflight_result.json` beside it |

## The verbatim rule here

The two patched files are listed in `tests/test_verbatim_pipeline.py::PATCHED` with their legacy sha256,
their preamble-block count and a reason. The proof is the same normalise-and-compare one the units get:
delete the declared preamble block, unwrap the `require_readable`/`require_writable` guards, fold every
resolver call back to the literal it resolves to on this machine, and the result must be byte-identical
to the legacy file. `tests/test_paths.py` pins each rewritten value against the literal extracted from
the legacy file at test time, so a rewrite that still *looks* like path resolution but points somewhere
else fails there too.
