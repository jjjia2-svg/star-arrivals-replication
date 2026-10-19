# `pipeline/rosters/` — who counts as a colleague

The rosters are the population every estimate in this paper is computed over: when a star arrives at
a department, the roster says who was there to be affected. Four of them are frozen in
`data/raw_verified/`. **All four are re-built and compared here.** Two of the producers are ordinary
ports of surviving scripts; two were recovered from the author's recorded command history, which is a
different kind of claim and is labelled as one throughout.

| frozen artifact | rows / people | producer | provenance | this repo |
|---|---|---|---|---|
| `roster_chemmath_verified.parquet` | 1,550 / 1,484 | `merge_chemmath_verified_v2.py` | ported (file survives) | **re-run, content-equal — and byte-identical** |
| `roster_gold_chemistry.parquet` | 533 / 518 | `00c_prep_final_population.py` | ported (file survives) | **re-run, content-equal** |
| `roster_gold_math_stats.parquet` | 580 / 573 | `00c_prep_final_population.py` | ported (file survives) | **re-run, content-equal** |
| `roster_econ_verified.parquet` | 920 / 920 | `merge_roster.py` | **recovered from recorded command history** | **re-run, content-equal — and byte-identical** |

```
python3 pipeline/rosters/run_rosters.py --list
python3 pipeline/rosters/run_rosters.py merge        # ~2 s  chem/math human-verification merge
python3 pipeline/rosters/run_rosters.py variants     # ~0.3 s the rank_tag ladder: inc / incamb
python3 pipeline/rosters/run_rosters.py incfel       # ~0.5 s the middle rung (recovered)
python3 pipeline/rosters/run_rosters.py final        # ~0.2 s the final population (incfel ∪ centres)
python3 pipeline/rosters/run_rosters.py econ-audit   # ~1.5 s the 994-row audit + 22 review batches
python3 pipeline/rosters/run_rosters.py econ-merge   # ~0.3 s the economics roster (recovered)
```

No SSD (except `econ-audit`), no network, no cloud. Every stage reads the human-verification evidence
from the read-only legacy tree and writes into the git-ignored `output/rosters/` scratch tree.
`tests/test_pipeline_rebuild.py` (sections 9 and 10) runs all six and does the comparisons.

> **Privacy.** The evidence these stages read — 22 econ batch files, 22 returned batches, the
> 994-row audit table, the 61+13+5 chem/math batches, the `collect/` scrapes — carries real names,
> staff-page and ORCID URLs, and free-text human notes. None of it is in this public package, and the
> stages that read it cannot run without it. It is planned for a restricted-access archive deposit
> (no DOI yet).

---

## Provenance

### `merge_chemmath_verified_v2.py` — the producer, proven by re-execution

The directory holds two merge scripts, `merge_chemmath_verified.py` (mtime 2026-08-10 **17:47:19**)
and `merge_chemmath_verified_v2.py` (**18:14:15**), and the six outputs are all stamped
**18:43:48–49**. The recon report inferred v2 from that ordering. **The inference is not sound on
its own** and it was re-checked here: an mtime records when a file was last *edited*, not when it
ran, so a 17:47 script can perfectly well have produced an 18:43 output — and v1 writes the *same
five basenames* as v2, so the filenames do not discriminate either. (M1 was bitten by the mirror
image of this: `p3_topicpair/code/run_p3_tp.R` was patched *after* the gold standard was written,
and the later file was not the producer.)

Three findings settle it, in increasing strength:

1. **v1 cannot have written one of the six.** `merge_stats_v2.json` (18:43:49) is written at v2 line
   429 (`json.dump(stats, open(.../merge_stats_v2.json, "w"))`). v1 has no such write — line 309
   only *prints* its stats. All six outputs are stamped in the same second, so one run wrote them;
   only v2 writes that one.
2. **v1 could run, but not on this evidence.** Its `assert len(vfs) == 61` passes — there really are
   61 files in `verify/verified/` — so v1 is not blocked. What it never reads is the 13 gap-fill and
   5 rematch batches, and the `rejected_persons_chemmath_prev_2026-08-10.csv` snapshot (18:35:49)
   that v2 uses to stay idempotent. Its output therefore *cannot contain* those people and cannot be
   the frozen 1,550-row roster.
3. **v2 re-executed today reproduces the frozen parquet byte for byte**, and all five ledgers byte
   for byte. That is the evidence that does not depend on any timestamp.

v1 is recorded as superseded and **not ported**. Its own outputs survive in
`verify/_backup_pre_gapfill_2026-08-10/`, which v2 creates before overwriting them — note those
copies are stamped **17:45**, ~94 seconds *before* v1's own mtime, so the v1 on disk is not
byte-for-byte the code that wrote even them. One more reason file order is a hint, not a proof.

`00_prep_inputs.py` is likewise **not ported**: its roster output is the known-bad whole-table one
(all 1,550 rows, no `rank_tag` filter) that `00b`/`00c` exist to replace.

### The gold chain: `00b` → `00b2` (recovered) → `00c` → `70`

* **`00b_prep_roster_variants.py`** (mtime 20:34:18; `data/{inc,incamb}/` at 20:34:24) cuts the
  verified roster on `rank_tag` and folds in two late-collected events. Re-run; all four rosters
  content-equal to the legacy run (`inc` 283 / 366, `incamb` 472 / 622).
* **`00b2_prep_incfel_variant.py`** — the middle rung, recovered (below).
* **`00c_prep_final_population.py`** (21:07:27; `data/final/` at 21:07:40) unions the `incfel`
  roster with the research-centre academic layer — the author's 2026-08-10 ruling that a research
  centre counts as a department. Re-run; both outputs content-equal to the frozen artifacts.
* **`70_prep_fnfix_inputs.py`** builds the fn-fix variant's inputs. Ported for completeness and
  **not run**: it walks the live OpenAlex works API for every newly added star, and a fresh call
  today returns *different* data — the address back-fill defect the fn-fix exists to correct. Its
  roster step is one line, `shutil.copyfile(data/final → data/fnfix)`, so the repo **asserts the
  identity it produced instead of repeating it**: `data/final`, `data/fnfix` and
  `data/raw_verified/roster_gold_{chemistry,math_stats}.parquet` are one file by sha256.

### Two producers that were never files — recovered from recorded command history

This is the part to read carefully, because it is the one claim in this directory that is not "we
copied a script that was on disk".

Task 5 first reported the economics roster and the `incfel` rung as having **no producer anywhere**,
after five on-disk searches, each with a positive control. Every one of those searches looked for a
**file**. These producers were never files in any tree: two were written into a temporary working
directory the OS has since reclaimed, and the third never had a filename at all — it ran once as a
heredoc inside a single shell call. Their content survives in the author's recorded command history,
which keeps every file write, edit and shell command with its exact arguments. That record is private
and is not part of this package.

**What was done, stated plainly: these three files were not copied from surviving scripts. They were
reconstructed by replaying the recorded operations in order.**

| repo file | recorded operations replayed |
|---|---|
| `econ_roster_verify_2026-08-09/code/merge_roster.py` | 1 write + 9 edits |
| `econ_roster_verify_2026-08-09/code/build_audit.py` | 1 write + 2 edits + 1 in-place shell patch |
| `multidisc_gold_2026-08-10/code/00b2_prep_incfel_variant.py` | 1 inline heredoc at `2026-08-10T10:38:27.165Z`, lifted whole |

The workflow definition that drove the whole economics round survives intact and was read as
evidence, not ported. It hard-codes the output directory and declares, as required
outputs, every artifact the first version of this note called orphaned.

**The replay is mechanical, and its rules are what keep it from becoming invention.** The replay
starts the file at the recorded write, requires each edit's old text to match exactly once, and
**reads** an in-place shell patch rather than executing it (parsed with `ast`, accepted only as a
chain of literal `str.replace` calls). No line is written by hand; no gap is filled by inference; a
mismatch stops the replay. The private repository pins each replay's sha256 and requires the ported
copy to normalise back to exactly those bytes.

**Why the reconstruction is trustworthy — the only argument that counts, and it is empirical:**

* `merge_roster.py` rebuilds `data/raw_verified/roster_econ_verified.parquet` **byte for byte**
  (`cbcf11ef…` on both sides, three consecutive runs; that is the private original: the published
  file has the personal columns removed, see `HASH_CROSSWALK.md`) and `econ_roster_verified_all.csv` byte for
  byte. Nothing else on this machine does that.
* `build_audit.py` rebuilds the 994-row audit table **and all 22 review batch files** byte for byte.
* `00b2_prep_incfel_variant.py` rebuilds both `incfel` rosters content-equal (396 / 384 and
  552 / 545), and writes the same two configs.

**One divergence, registered rather than smoothed over.** `rejected_persons.csv` does *not* come
back identical: 74 rows and all 12 rebuilt columns match row for row, but the legacy copy carries a
13th column, `reject_cause`, and its mtime is 22:41:01 — 66 seconds after the 22:39:55 wave. A
follow-up enrichment step (now recovered as `add_reject_cause.py`). See `../NOT_REPRODUCIBLE.md`.

**One caution about shell patches, learned the hard way here.** The first replay of `build_audit.py`
skipped the in-place shell patch and produced a file that got the 994 rows, the columns and the
`author_id` set right — and 154 rows of one free-text column wrong. Skipping shell edits does not
make a recovery conservative; it makes it silently wrong. The recorded command also contained
`rm -f "<legacy tree>/batches/"*.csv`, which is why the tool reads patches instead of running them.

### What is still irreproducible

The **840 economics and 2,593 chem/math human verification judgements** themselves, the
`reject_cause` enrichment step, and two undocumented copy steps (`ev20`, `noA5044701593`). All registered in
`../NOT_REPRODUCIBLE.md` with what a replicator can check instead.

---

## Byte-reproducibility (more evidence for plan deviation D1)

Measured, not assumed. Whether a rebuild is byte-identical here depends entirely on **which library
writes the parquet**:

| stage | writer | byte-stable? |
|---|---|---|
| `merge` (chem/math roster), `econ-merge` (econ roster) | pandas `to_parquet` | **yes** — 3 consecutive runs, identical sha256, equal to the frozen file |
| `variants`, `incfel`, `final` | DuckDB `COPY … TO … PARQUET` | **no** |

Four runs of `final` produced **eight distinct digests** and not one matched the frozen file, on
files of identical length: the row order moves between runs. `content_equal`'s `EXCEPT ALL` reports
EQUAL every time, which is exactly why D1 makes content-equality the gate and byte-equality an
observation. An earlier version of this README claimed `roster_gold_math_stats.parquet` came back
bit-identical; that was one lucky run and the claim was false.

---

## How the stages run without writing where the original wrote

Every roster script has the same defect: **one absolute constant that is at once its input root and
its output root** (`BASE` in the two merges, `ROOT` in `00b`/`00b2`/`00c`/`build_audit`). Running one
in place would rewrite the 2026-08-09/08-10 human-verification evidence inside the read-only legacy
tree — the chem/math merge re-creates `verify/_backup_pre_gapfill_2026-08-10` and overwrites
`rejected_persons_chemmath.csv`.

Neither existing mechanism covers that. `drivers/run_driver.py` resolves a driver's declared *output*
constant, which cannot work when the same constant is also where the inputs are; `fwci/run_fwci.py`
moves the *script*, which cannot work when the destination is an absolute literal rather than
`__file__`. So `run_rosters.py` does both:

1. it builds a **staging mirror** of the legacy run directory under `output/rosters/<stage>/` and
   **symlinks the inputs in** — directories a stage writes into are created REAL and only the leaves
   are linked, so nothing can be written back through an input link;
2. the ported root constant goes through `pipeline.lib.paths.staged_run_dir()`, which returns that
   mirror and **raises when no launcher staged one** — there is no configuration in which a ported
   roster script writes where the original run wrote;
3. for `00b` alone — the one script whose output really does hang off `__file__` — the script is
   additionally hard-linked into the mirror (the `run_fwci.py` pattern), bytes checked.

`staged_run_dir()` relaxes exactly one of `output_target()`'s rules: a staging mirror is allowed to
be non-empty, because it must already hold the inputs. Every other refusal is kept and tested
(legacy root, repo source tree, relative path, missing mirror, and a symlink resolving into any of
those). What it does **not** judge is the *interior* of a mirror — see `../NOT_REPRODUCIBLE.md`.

**`$SAR_OUT_ROOT` and the one stage it cannot move.** It relocates the scratch tree to
`<root>/rosters/<stage>` and is judged by the same write barrier. Five of the six stages run from
any root. `variants` cannot: it is the stage whose script is relocated, and the ported preamble
finds this repository by walking up to a directory named `rosters` and taking its grandparent — true
under `<repo>/output/rosters`, false anywhere else. The launcher checks that before staging anything
and refuses with the reason, so this fails loudly rather than as an ImportError inside a subprocess.

**Housekeeping notes for anyone reading a run directory.** The chem/math merge re-creates an empty
`verify/_backup_pre_gapfill_2026-08-10/` inside its mirror — it backs up prior outputs, and a fresh
mirror has none, so the directory is correctly empty and is not a failure. And `merge_roster.py`
ends with four diagnostic writes into the temporary working directory it was authored in (in this
package: `/private/tmp/removed-session-directory`); that directory is gone, so the launcher re-creates it empty, lets the verbatim tail run, and removes it again. Those
four files are diagnostics (the same content is printed to stdout), not artifacts.

The ported files are byte-for-byte copies of their sources apart from that single constant;
`tests/test_verbatim_pipeline.py` proves it by undoing the substitution and requiring the result to
equal the legacy bytes — or, for the recovered three, the replay's bytes.
