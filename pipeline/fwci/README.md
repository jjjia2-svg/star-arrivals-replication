# `pipeline/fwci` — the field baseline the FWCI outcome is divided by

FWCI (field-weighted citation impact) = a paper's citations divided by the average citations of every
paper in the same cell, where a cell is `(subfield, publication year, work type)`. The frozen P1
frames' outcome variable is built from it, so the table in this layer sits underneath every headline
coefficient in the paper.

Two scripts are ported here, both byte-for-byte except their path constants
(`tests/test_verbatim_pipeline.py` proves it by normalising the port back to the legacy bytes):

| stage | script | runtime | run by M3? |
|---|---|---|---|
| `scan` | `fwci_baseline_fullsnapshot_2026-08-09/code/01_scan_full_snapshot.py` | **37.0 min** (measured), 510,372,821 records | **no — OFF by default** |
| `build` | `fwci_fullsnapshot_rebuild_2026-08-09/code/01_build_expected_full.py` | ~1 s | **yes, and its output is checked** |

    python3 pipeline/fwci/run_fwci.py --list
    python3 pipeline/fwci/run_fwci.py build          # rebuilds the expected table into output/fwci/

## Provenance — which script produced which surviving artifact

Established the same way M1 established `run_p3_tp.R` and T2 established the U3 driver: code mtime
against output mtime, the artifact's own provenance record, and a search for competing copies.

**`01_scan_full_snapshot.py` → `fwci_baseline_pop_full.parquet` (543,037 cells, 4,143,092 B).**
Code mtime `2026-08-09 18:47:54`; output `19:25:55`, i.e. 38 min 01 s later, which is the measured
37.0 min scan (`data/fwci/scan_full_2026-08-09.log`: `[scan] scan done in 37.0 min`) plus the
0.76 min merge the manifest records — 37.8 min, the rest being start-up and the shard walk. `scan_manifest.json` (same second as the
parquet) names the output file explicitly and carries the counts that reconcile it to the snapshot:
2,446 shards, `manifest_record_count = total_lines_read = 510,372,821`, `bad_lines = 0`,
`shard_read_mismatches = 0`, 375,548,859 cellable works, 2,876,959,267 citations,
`snapshot_manifest_date = 2026-06-26`. `gate_a_reconcile.json` (19:26) and
`gate_b_cell_recount.json` (19:56, a 30-minute independent re-scan) are its audits, both PASS.
**No competing copy exists**: a search of the whole thesis tree and the data disk finds exactly one
file with this basename. Verdict: **sole producer**.

**`01_build_expected_full.py` → `fwci_expected_fullsnapshot_2026-08-09.parquet` (130,061 cells,
633,092 B) and `fwci_expected_oldpop_2026-08-09.parquet` (43,175 cells).** Code mtime
`2026-08-09 20:03:20`; both parquets `20:03:28` and the record `g_step1_expected.json` `20:03:29` —
eight seconds, which is the whole runtime. The record names both output paths, both cell counts
(130,061 / 43,175), the 60,504 zero-expected cells, and the oracle check (`build_fwci_baseline`, the
production function, recomputed all 130,061 cells with 0 mismatches). The output basename is
hard-coded in the script. **No competing copy exists** (same search). Verdict: **sole producer**.

**Nothing here was patched after its output was written** — the trap M1 hit with `run_p3_tp.R` and T2
re-tested for the U3 driver. Both code mtimes PRECEDE their outputs, and by an interval that matches
the measured runtime rather than merely being positive.

**Which directory superseded which.** Three FWCI runs happened on 2026-08-09 in strict order.
`multidisc_fwci_selfbuilt` (17:10–17:25) built a denominator from the existing seed-subset
population, which made "FWCI = 1.0" mean "average of our own network" rather than the world average;
the author ruled that day to switch to a world baseline. `fwci_baseline_fullsnapshot` (18:47–19:56)
therefore rescanned the entire snapshot with no filtering. `fwci_fullsnapshot_rebuild` (20:03–20:26)
folded that into the 4-column expected table. The old denominator was inflated by a median 1.66× /
weighted 2.20×, so the pre-rebuild FWCI was systematically compressed — which is why the `_new` /
`_fullsnap` suffixes on the frozen frames mean "full-snapshot denominator" and the `_machineold` /
`_denomonly` siblings are attribution controls that are correctly not shipped.

## The signed caliber the expected table encodes

Read live from `pipeline/contracts/redlines.yaml` by the ported script, never restated in code:

* cell = `(subfield_id, publication_year, work_type)`; `expected = citation_sum / work_count`
* `included_types = [article, review]` — the same whitelist on numerator and denominator
* `paratext_symmetric_drop = true`; `denominator_leave_star = false`
* `missing_fill = NA`, **never 0**. 60,504 of the 130,061 cells have `expected = 0`, and
  `compute_fwci` maps those to `fwci = NA, reason = "zero_expected_cell"`. Any reimplementation that
  divides by zero or fills 0 moves the headline coefficient.
* The paratext symmetric drop is measurably a no-op on this snapshot (every `is_paratext=True` work
  also has `type = 'paratext'`, already excluded by the whitelist): the run record reports 0 cells
  affected. The subtraction is performed anyway, as evidence that the caliber is implemented.
* 26.4% of snapshot works are not cellable (106.5 M missing subfield, 19.5 M missing year, 8.8 M
  both) and are excluded by design.

## What `build` proves, and what it does not

Running `build` re-derives the expected table from the frozen population table and compares it with
`tools/content_equal.py` against the frozen copy — `tests/test_pipeline_rebuild.py` does exactly
that. The formula that runs is **this repository's**: the launcher imports `common._redlines` and
`m5_output.fwci_baseline_build` from `pipeline/units/` before the script starts, so the script's own
`sys.path.insert(0, …multiplex_pipeline/units…)` — a line holding no absolute path, therefore
untouchable under the verbatim rule — finds them already in `sys.modules`. The two copies are
byte-identical anyway; this only decides which file is read.

**Stated limitation — `build` needs BOTH the legacy tree and the mounted data disk.** Two inputs,
neither satisfiable from this repo alone:

1. `NEWPOP` is built from `ROOT` as `f"{ROOT}/v2_output/…/fwci_baseline_pop_full.parquet"`. That line
   holds no absolute path, so `ROOT` (which does) is the only part the port could resolve — the
   destination is therefore the **legacy thesis tree**. The identical file *is* frozen here at
   `data/fwci/fwci_baseline_pop_full.parquet` with its sha256 in `data/MANIFEST.sha256`, so the input
   can be verified independently; making the script *read* the repo copy means rewriting a line that
   is not a path-resolution hunk, which M3 does not allow.
2. `OLDPOP` is the **514 MB pre-rebuild denominator on the external data disk**
   (`<derived>/u1_edges_full_2026-07-05/fwci_baseline_pop`). It is **not frozen and not obtainable**
   from this repo — 514 MB is past what belongs in git, and it feeds only the contrast arm.

So on a replicator's machine — no legacy tree, no data disk — **`build` cannot run**, and the two
Task-4 rebuild tests **skip** (`needs_fwci_inputs` checks for both). What a replicator can still
check: the ten frozen files against `data/MANIFEST.sha256`, the scan's self-reconciliation inside
`scan_manifest.json`, and the paper's funnel numbers, which `analysis/paper/ledger_funnel.py` now
derives from the frozen records rather than from the legacy tree. Both limitations go to Task 8.

## Where the output goes, and why the launcher exists

Both scripts derive every output location from their own `__file__`:
`BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` (build) and
`BASE = Path(__file__).resolve().parent.parent` (scan). Neither line holds an absolute path, so
neither may be touched — the same bind `step3_run_u6.py`'s `U6_OUT` is in. `drivers/run_driver.py`
solves its case by resolving the driver's declared output constant first; that cannot work here,
because the constant is computed from `__file__` and re-computing it changes nothing.

So `run_fwci.py` moves the file rather than the constant: it stages a run directory at
`<scratch>/<legacy run directory name>/code/`, **hard-links** the ported script in (a symlink would
not do — `scan`'s `Path(__file__).resolve()` follows one and would land back in the repo), asserts
the staged file's sha256 equals the ported file's, and runs that. The scratch root is
`output/fwci` — git-ignored, cleared before each run — and it is passed through `output_target()`, so
a scratch root that has been pointed into a legacy tree or a frozen directory is refused. `output/`
is never read by the analysis layer, so a rebuild cannot contaminate a frozen artifact.

**Running a ported script directly is refused** (T4 review MAJOR-1). `python3 pipeline/fwci/…/01_scan_full_snapshot.py`
used to start the 37-minute pass with no gate at all, and created `{data,logs,partial}/` inside the
tracked tree — untracked but not git-ignored, with a second, unhashed `fwci_baseline_pop_full.parquet`
sharing the frozen artifact's basename. The refusal now lives in `pipeline/lib/paths.py`
(`refuse_unstaged_in_place_run`), attaches to the `require_readable` guard the ported path constants
already call at import, and fires before `main()` — so it costs the port nothing and covers every
ported script that resolves a root, the drivers included. A launcher exempts its own staged run with
an in-process marker scoped to the `runpy` call (T8; it used to be `$SAR_STAGED_RUN`, an environment
variable the refusal message named, so exporting it re-enabled the hazard — it no longer does
anything). Separately, `output_target()` now refuses any destination inside the repository that is
not under `output/`.

`$SAR_OUT_ROOT` moves the scratch root and is judged by the same barrier. It is single-use, exactly
as for the ported drivers: the second run into the same root is refused because the destination is by
then non-empty. Use a fresh root to re-run. Note that the scratch root's basename must stay `fwci` —
the ported preamble finds the repo by walking up to a directory of that name, and the redirect
preserves the basename, so this holds for both the default and a redirected root. When the root is
redirected outside the repository the preamble's walk-up lands somewhere harmless and the import
still succeeds, because the launcher has already imported `pipeline.lib.paths`.

## Why `scan` stays off

M3's plan forbids expensive reruns. The scan streams **665.7 GB** of compressed works shards (the
`gz_bytes` its own log records; the whole snapshot directory is 694 GiB) and takes a measured
**37.0 minutes**; its output survives, is frozen, and is hashed; and its manifests are the source of
the funnel numbers the paper already cites. `run_fwci.py scan` prints the full cost and exits 2
unless `--execute` is given — **and the cost is not prose**: `_scan_cost()` builds every figure in it
by reading `data/fwci/scan_manifest.json` and `data/fwci/scan_full_2026-08-09.log`, so a number in
the warning cannot drift from the record it claims to quote.

`orjson` is a **hard requirement** of the scanner, not a preference. `--json-lib` defaults to
`orjson` and every worker calls `set_json_lib("orjson")`, which raises `SystemExit` with an
orjson-not-installed message when the module is absent — so without orjson the scan **fails outright**, it does not fall back.
Pass `--json-lib stdlib` instead (`run_fwci.py scan --execute --json-lib stdlib`, ~3× slower, ≈2 h);
the launcher forwards trailing arguments to the script. `orjson` is not pinned in
`setup/requirements.txt`; that belongs with the environment lock in Task 8.

The two audit gates that accompany the scan (`02_gate_a_reconcile.py`, `03_gate_b_cell_recount.py`)
are not ported: gate A re-reads the same manifest this repo freezes, and gate B is a second 30-minute
full-snapshot pass. Their verdicts are shipped as data (`data/fwci/gate_a_reconcile.json`,
`gate_b_cell_recount.json`, both PASS). `04_gate_c_old_vs_new.py` is dead code and is registered in
`pipeline/NOT_REPRODUCIBLE.md`.

## What is frozen, and where it came from

`data/fwci/`, all sha256-pinned in `data/MANIFEST.sha256` and copied by `tools/import_frozen.py`:

| file | bytes | rows | producer |
|---|---|---|---|
| `fwci_baseline_pop_full.parquet` | 4,143,092 | 543,037 | `scan` (37.0 min) |
| `fwci_expected_fullsnapshot_2026-08-09.parquet` | 633,092 | 130,061 | `build` — **the table the frames use** |
| `fwci_expected_oldpop_2026-08-09.parquet` | 416,619 | 43,175 | `build`, contrast arm |
| `econ_units_2026-08-09.parquet` | 2,062,404 | 160,437 | `03_econ_anchor_test.py` — **not ported and not run in Task 4**; it needs the data disk and belongs to the frames task. Frozen here because the econ frame builder consumes it, and registered in `pipeline/NOT_REPRODUCIBLE.md` |
| `scan_manifest.json`, `gate_a_reconcile.json`, `gate_b_cell_recount.json`, `g_step1_expected.json`, `g_c_old_vs_new.json` | small | — | the run records and audit verdicts quoted above. `analysis/paper/ledger_funnel.py` reads the first two from **here**, so the paper's funnel numbers no longer need the legacy tree |
| `scan_full_2026-08-09.log` | 32,618 | — | the scan's console log — the only surviving source for the measured 37.0 min, the 13 workers, the 229,785 rec/s and the 665,688,383,258 streamed `gz_bytes`. `run_fwci.py` builds its cost warning from it |

The 108 MB `partial/` tree from the scan is deliberately not shipped: it is 299 resumable shard
tables whose sum is the frozen population table.
