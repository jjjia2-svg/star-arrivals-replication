# `pipeline/frames/` — the frozen frames and what rebuilds them

`data/frames/` holds the 21 files the whole analysis layer reads. This directory holds the code that
produces them, ported from the legacy run directories, plus the launcher that can run it.

**The acceptance result (M3 Task 7): 19 of 21 rebuild EQUAL under the D1 criterion, 0 skipped, 0
registered as unreproducible, and 2 do not match byte for byte.** The two are
`p1_frame_chemistry.csv` and `p1_frame_math_stats.csv`; see [The one thing that does not
match](#the-one-thing-that-does-not-match) — and note that the *estimates* those two frames feed
reproduce exactly, which is what settles how much the byte difference matters.

The table is not a print statement: `tests/test_pipeline_rebuild.py::EXPECTED_ACCEPTANCE` pins
frame → (builder, mode, verdict) for all 21, and every comparison builds the rebuilt path from the
producing run and checks it against the producer's own output report, so a case cannot record a
verdict for a comparison it did not make.

The D1 criterion (plan deviation D1): **CSV → sha256 of the whole file, nothing normalised;
parquet → DuckDB `EXCEPT ALL` in both directions plus row counts plus the schema.** Every acceptance
assertion goes through `tools/content_equal.py`, not through `make_slim.py`'s own `content_equal`,
which has no schema check and compares a caller-chosen column subset.

```bash
python3 pipeline/frames/run_frames.py --list       # the stages, their cost, and what each rebuilds
python3 pipeline/frames/run_frames.py afar         # ~5 s, no data disk
python3 pipeline/frames/run_frames.py p1-econ --execute        # needs the data disk
python3 -m pytest -q tests/test_pipeline_rebuild.py -k t7 -s   # the whole acceptance proof, ~1 min
```

---

## 1. The acceptance table

Measured on the author's machine (15 cores, 25.8 GB RAM, duckdb 1.5.4, SSD mounted), 2026-08-26.
Runtime and peak RSS are per launcher stage, so frames produced by one stage share a figure.

| # | frozen frame | builder | inputs | runtime | peak RSS | mode | rows | verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | `p3_afar_econ.parquet` | `50_leftbehind_build.py` | `pairs_unified.csv` 663 MB + P1/P2 econ | 4.5 s | 2,252 MB | content | 394,221 | **EQUAL** |
| 2 | `p3_afar_chemistry.parquet` | `50_leftbehind_build.py` | `pairs_none.parquet` + P1/P2 chem | " | " | content | 37,950 | **EQUAL** |
| 3 | `p3_afar_math_stats.parquet` | `50_leftbehind_build.py` | `pairs_none.parquet` + P1/P2 math | " | " | content | 44,706 | **EQUAL** |
| 4 | `p3_afar_counts.csv` | `50_leftbehind_build.py` | all 15 cells of the same run | " | " | bytes | 15 | **EQUAL** |
| 5 | `p3_afar_tau_profile.csv` | `60_lb_tau.py` | `lb_manifest.json` + 12 cells | " | " | bytes | 156 | **EQUAL** |
| 6 | `p3_afar_speed_bracket.csv` | `speed_bracket.py` **[RECOVERED]** | 9 cell parquets | 0.2 s | 129 MB | bytes | 9 | **EQUAL** |
| 7 | `p1_frame_econ_old79.csv` | `split_old79_new38.py` **[RECOVERED]** | P1 econ + the 38-event list | 0.5 s | 192 MB | bytes | 75,746 | **EQUAL** |
| 8 | `p1_frame_econ_new38.csv` | `split_old79_new38.py` **[RECOVERED]** | " | " | " | bytes | 43,659 | **EQUAL** |
| 9 | `p1_events_ledger_econ.csv` | `01_merge_inputs.py` | 79-event ledger + 38 new events | 0.2 s | 50 MB | bytes | 117 | **EQUAL** |
| 10 | `p3_slim_ev_math_stats.parquet` | `make_slim.py` | `pairs_none.parquet` 326 KB | 0.04 s | — | content | 1,322,287 | **EQUAL** |
| 11 | `p3_slim_math_stats.parquet` | `make_slim.py` | " (same build, projected) | " | — | content | 1,322,287 | **EQUAL** ¹ |
| 12 | `p3_slim_ev_chemistry.parquet` | `make_slim.py` | `pairs_none.parquet` 1.18 MB | 0.1 s | — | content | 4,507,601 | **EQUAL** |
| 13 | `p3_slim_chemistry.parquet` | `make_slim.py` | " (same build, projected) | " | — | content | 4,507,601 | **EQUAL** ¹ |
| 14 | `p3_slim_ev_econ.parquet` | `make_slim.py` | `pairs_unified.csv` 663 MB | 2.0 s | — | content | 12,178,194 | **EQUAL** |
| 15 | `p3_slim_econ.parquet` | `make_slim.py` | " (same build, projected) | " | — | content | 12,178,194 | **EQUAL** ¹ |
| 16 | `p2_becoming_chemistry.csv` | `30_build_panels23_gold.py` | SSD `u1_edges_full_2026-07-05` 1.0 GB | 1.5 s | 803 MB | bytes | 70,545 | **EQUAL** |
| 17 | `p2_becoming_math_stats.csv` | `30_build_panels23_gold.py` | " | 1.1 s | 477 MB | bytes | 35,316 | **EQUAL** |
| 18 | `p2_becoming_econ.csv` | `10_panels23_econ920.py` | SSD `u1_full_11school_2026-07-16` 1.8 GB | 23.6 s | 5,222 MB | bytes | 181,695 | **EQUAL** |
| 19 | `p1_frame_econ.csv` | `04_rebuild_y.py` | SSD `u1_full_11school_2026-07-16` + FWCI | 4.8 s | 833 MB | bytes | 119,405 | **EQUAL** |
| 20 | `p1_frame_chemistry.csv` | `20_rebuild_y_gold.py` | SSD `u1_edges_full_2026-07-05` 2.5 GB | 5.1 s | 840 MB | bytes | 46,552 | **NOT BYTE-EQUAL** ² |
| 21 | `p1_frame_math_stats.csv` | `20_rebuild_y_gold.py` | " | 2.6 s | 558 MB | bytes | 23,232 | **NOT BYTE-EQUAL** ² |

¹ one declared type axis, see §2.  ² see §5.

Total added compute for the whole proof: **under one minute** of CPU with the data disk warm. Recon
budgeted 10–15 minutes; the two figures it estimated highest were both cold-cache measurements
(`04_rebuild_y.py` "≈3 min" runs in 4.8 s warm, `50_leftbehind_build.py` "≤5 min" in 4.5 s).

`analysis/run_all.sh`'s own estimation layer is unaffected and unmoved: this table is about
CONSTRUCTION, and the expensive thing in this project is estimation.

## 2. The three declared type axes

`tools/content_equal.py` treats a schema difference as NOT EQUAL. Three frames need one narrow,
per-frame exception, declared in `tests/test_pipeline_rebuild.py::SLIM_CASES` and never globally:

| frame | column | rebuild | frozen | why the frozen file is what it is |
|---|---|---|---|---|
| `p3_slim_econ.parquet` | `grp` | INTEGER | BIGINT | the legacy econ slim was an inline heredoc in `econ_fnfix_2026-08-15/run_all.sh` that never cast its `DENSE_RANK()` to INTEGER |
| `p3_slim_chemistry.parquet` | `y`, `D` | TINYINT | INTEGER | `30_build_panels23_gold.py:284` casts y/D to INTEGER; `make_slim_ev.py` casts to TINYINT, and the repo ships the latter as its single implementation |
| `p3_slim_math_stats.parquet` | `y`, `D` | TINYINT | INTEGER | " |

All three are inside `LOSSLESS_INT_WIDENING`, the only family the harness accepts since the T3
review restricted the axis (a lossy declaration made `2^53+1` BIGINT read equal to `2^53` DOUBLE).
The axis is direction-sensitive and does not weaken the row comparison.

**The `ev` asymmetry is not a type difference and is not handled by the axis.** The frozen non-`ev`
slims have a genuinely different column SET. So one build per field is compared TWICE: once against
`p3_slim_ev_<field>` (identical schema, no axis), and once against `p3_slim_<field>` after
projecting onto the frozen file's columns — with an assertion that the projection dropped exactly
`ev` and nothing else, so a subset comparison cannot hide a column difference.

## 3. Provenance, per builder

Evidence that does not rest on mtime alone, per the M1 / T5 / T6 precedent.

| ported file | is the producer because | patched |
|---|---|---|
| `p3_topicpair_2026-08-17/code/50_leftbehind_build.py` | it is the only writer of the five cells this stage produces (`95_amixed.py` writes the separate `A_mixed` cell), and re-running it reproduces `lb_counts.csv` byte for byte **including the three frozen topic cuts** (econ .3332 / chem .3427 / math .0885), which nothing else records | 1 hunk (`V`) |
| `p3_topicpair_2026-08-17/code/60_lb_tau.py` | it reads `lb_manifest.json`, which only `50_` writes, and reproduces `lb_tau_profile.csv` byte for byte | **verbatim** |
| `econ_fnfix_2026-08-15/code/01_merge_inputs.py` | `logs/tail.log` puts it at stage 2/7, 04:09:50→04:09:56, and the rerun reproduces `event_ledger_fnfix.csv` byte for byte | 1 hunk (`ROOT`) |
| `econ_fnfix_2026-08-15/code/04_rebuild_y.py` | the rerun reproduces the 19,127,653-byte frozen frame byte for byte, three times out of three | 10 hunks |
| `econ_fnfix_2026-08-15/code/10_panels23_econ920.py` | the rerun reproduces `p2_becoming_econ.csv` byte for byte **and** the 662,663,276-byte `pairs_unified.csv` byte for byte (sha256 `d107b584…`), which is the intermediate every econ slim and the econ A_far cell read | 8 hunks |
| `multidisc_gold_2026-08-10/code/20_rebuild_y_gold.py` | the rerun reproduces every column of the frozen frame except the two FWCI ratio columns, and those to within 3 ULP — see §5 | 8 hunks |
| `multidisc_gold_2026-08-10/code/30_build_panels23_gold.py` | the rerun reproduces both frozen P2 panels byte for byte | 5 hunks |

Three traps recon flagged and this port honours: the chem/math P1 frames come from stage 3
(`20_rebuild_y_gold.py`), **not** from `10_build_union_frame_gold.py`, whose output is stage 3's
input; the econ builders are machine-generated at run time by `02_clone_chain.py`, so their `code/`
mtimes are worthless as evidence (the logs are used instead); and `GOLDVAR=fnfix` must be set or
every gold script silently reads and writes the wrong variant (hazard H4). The launcher sets it and
prints it.

`analysis/robustness/p3_afar/build_afar.py` (M1) stays where it is and is unchanged. It ports the
**A_far cell only**; `50_leftbehind_build.py` here is the whole five-cell script, so the A_far cut is
now produced by the same run that produces the counts table recording it.

## 4. The two producers recovered from recorded command history

Recon and plan deviation D2 said no builder existed for either. Both existed; neither was ever a
file, which is why every on-disk search failed. A search of the author's recorded command history
(for commands whose CONTENT names the artifact, not only for commands that write a file of the right
name) found both.

| recovered file | evidence |
|---|---|
| `econ_fnfix_2026-08-15/code/split_old79_new38.py` | a heredoc inside one shell call at `2026-08-15T18:15:00.361Z`, i.e. **04:15:00 local — the exact mtime of both frozen subsets**. Lifted whole from the recorded command; sha256 `ea63b063…` |
| `p3_topicpair_2026-08-17/code/speed_bracket.py` | a heredoc at `2026-08-17T22:12:52.577Z` = **08:12:52 local, the frozen file's mtime to the second**. An earlier attempt at 22:12:34 is recorded as having FAILED (`TypeError: unsupported operand type(s) for /: 'decimal.Decimal' and 'float'`), which is what settles which of the two candidate ops is the producer. sha256 `ea68938c…` (of the private original; the published file's value is in `HASH_CROSSWALK.md`) |

Both rebuild their frozen artifact **byte for byte**, which is the external, empirical proof that the
replay is the original and not a plausible substitute.

The splitter also corrects recon's reconstruction of its own rule. Recon inferred, from the frozen
bytes, that the split was a `csv.reader` → `csv.writer` pass with the output opened **without**
`newline=""`. Two of its three inferences hold (order-preserving partition on `event_id`, field text
copied verbatim rather than round-tripped through `float`); the third is wrong in mechanism: the file
IS opened with `newline=""`, and the CRLF is `csv.DictWriter`'s default `lineterminator`. The
observable outcome is the same, which is exactly why an inferred rule is not evidence. **The CRLF is
visible in the comparison, not normalised away** — `tools/content_equal.py` hashes the whole file,
and `test_case8` pins that CRLF vs LF is NOT EQUAL.

## 5. The one thing that does not match

`p1_frame_chemistry.csv` and `p1_frame_math_stats.csv` do **not** rebuild byte-identically, and the
finding is that byte-equality for them is **unreachable, not merely unachieved**: the builder does
not agree with itself.

```
math_stats, three independent runs:  3,319,308 / 3,319,400 / 3,319,265 bytes   (frozen 3,319,405)
chemistry,  three independent runs:  7,239,495 / 7,238,951 / 7,239,229 bytes   (frozen 7,239,155)
```

Characterised, in `tests/test_pipeline_rebuild.py`:

* same row count, same header, and the **only** columns that ever differ are `fwci_frac` and
  `fwci_frac_ex_star` (how many rows differ varies from run to run — it is not a property of the
  file);
* every difference is at most **3 ULP**, relative ≤ 6.1e-16.

The mechanism is in the code, not the environment: `20_rebuild_y_gold.py:152-166` materialises its
per-work unit table with `.df()` from a DuckDB query that carries no `ORDER BY`, under
`PRAGMA threads=8`; line 189 then accumulates `a["ff_n"] += fc * val` in whatever order that parallel
scan returned. Floating-point addition is not associative, so the last bits move with the scan
schedule. This is hazard H1 — the licensed nondeterminism recon measured on the parquet side —
reaching a CSV frame. The sibling script acknowledges the same class in its own source
(`04_rebuild_y.py`, `REPRO_F32_TOL = 1e-6`), and `04_rebuild_y.py` itself is byte-stable because its
accumulation runs over `sorted(set(...))` and a JSONL read rather than over an unordered scan.

### And it does not reach a single reported number — measured, not argued

This is the question the byte difference actually poses, and it has an answer:

* **The estimates reproduce exactly.** Estimating from a REBUILT frame and comparing with
  `analysis/lib/compare_json` — which applies **no tolerance**, only dropping `secs`/`file` —
  gives `EQUAL` **four times out of four**: chemistry and math-stats, each from two independent
  rebuilds. The event-clustered arm (`P1evcl_chemistry`, `P1evcl_math_stats`) is `EQUAL` on the same
  rebuilt frames. That is the gate `analysis/run_all.sh` enforces on all 19 cells.
* **Where the residual sits.** Re-running the estimator at `digits=17` instead of the shipped
  `digits=8`, the noise does propagate and it stops at digit 16–17:

      math_stats union ATE   frozen -0.11637269450819823
                             rebuild 1 -0.11637269450819826   rebuild 2 -0.11637269450819825
      chemistry union ATE    frozen -0.25721299393188424   rebuild 1 and 2 identical to it

  Worst movement across all reported quantities: **1–3 ULP**. At the 8 significant digits the
  package stores and compares, nothing moves.
* **The control that makes that a measurement.** The SAME frozen frame estimated twice, at 17
  digits, also compares `EQUAL` (the only byte differences are `file` and `secs`). So the estimator
  is deterministic and any 17-digit movement above is attributable to the frame, not to the run.
* **The paper layer.** `analysis/paper/ledger_main.py` reads `fwci_frac` (pre-period balance means
  and quantiles rounded to 2 d.p.) and `analysis/paper/gaps_zero_dose.py` reads the same frames.
  Frozen vs rebuilt quantiles: `[0.0, 0.71, 2.65, 11.6]` max `226.0` (math) and
  `[0.41, 1.59, 4.3, 15.69]` max `118.6` (chem) — identical on both sides.

**So this is a documentation item, not an open choice.** No third D1 clause is needed and no
re-freeze is needed: the byte verdict stays NOT EQUAL, and it is recorded next to the measured fact
that everything downstream of these two frames reproduces exactly. Adding an outer `ORDER BY` to the
legacy query would make the bytes reproducible, but that is an algorithm change — M3 reports legacy
defects and does not fix them — so it is a candidate for a later milestone, not a gap here.

**Complete downstream exposure** (all four checked, none moves): `P1_chemistry`, `P1_math_stats`,
`P1evcl_chemistry`, `P1evcl_math_stats`, the chem/math A_far dose cut, `analysis/paper/ledger_main.py`
and `analysis/paper/gaps_zero_dose.py`.

**And the A_far cell does not inherit it.** The `afar` stage reads
`analysis_frame_{field}_new_gold_2026-08-10.csv` — these very files — from the legacy tree, which
looks alarming. It reads exactly three columns from them (`event_id`, `incumbent_person_id`,
`dose_topic`, at `50_leftbehind_build.py:46-48`), and the only columns that ever differ are
`fwci_frac` and `fwci_frac_ex_star`. The three A_far panels are content-EQUAL, which is the
empirical confirmation.

## 6. Running the layer

Stages are in `run_frames.py::STAGES`. Four need the data disk and are OFF until `--execute`; the
other four run on the boot volume alone. Each stage gets its own scratch subdirectory, staged from
`output/frames/` or from `$SAR_OUT_ROOT`, and each is judged by the write barrier before anything is
created: no stage can write into a legacy tree, into `data/frames/`, or anywhere in the repo outside
`output/`.

**Prefer an out-of-repo `$SAR_OUT_ROOT`.** On the author's machine `<repo>/output/` sat inside a cloud-synced
folder, and rebuilding into it during this task produced a `p1-econ 3` conflict copy mid-run — a
65,535-link directory the launcher then correctly refused as an entry it did not create. The
acceptance suite therefore runs every stage with a fresh `$SAR_OUT_ROOT` under `/private/tmp`.
`$SAR_OUT_ROOT` is single-use by design (the barrier refuses a root that already holds entries), so
each stage needs its own.

Two ported scripts (`04_rebuild_y.py`, `20_rebuild_y_gold.py`) reach the FWCI machinery with
`sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/…")`, where `ROOT` is the read-only legacy
tree. The launcher pre-imports this repository's `m5_output.fwci_baseline_build`,
`m5_output.fwci_raw` and `identity.output_rule` under those exact names first, so the insert is inert
and the y column is computed with the code this package ships. The copies are byte-identical;
`tests/test_verbatim_pipeline.py` proves it, and the run record prints each module's `__file__`.

`01_merge_inputs.py` has a live-OpenAlex branch (hazard H11). It is switched off the way the
2026-08-16 run switched it off — by the supplement JSONL being present as a staged input — and the
run prints a line saying the supplement already exists (4151 rows) and the fetch is skipped. A live re-fetch would be a different artifact,
not a reproduction.

## 7. What this layer does NOT reproduce

* **Depth.** These builders start from their immediate inputs. Full-depth reproduction additionally
  needs prodlib `build_frame.py`, `00_build_frame_econ920.py`, `10_build_union_frame_gold.py`,
  `70_prep_fnfix_inputs.py` and the whole U1–U6 chain on the data disk (696 GB in, ~17 h for U1).
* **Third-party reruns.** Tiers 1 and 2 both start from intermediates the package does not ship
  (`pairs_unified.csv` 663 MB, `pairs_none.parquet`, the SSD U1/U2 tables). The reproducibility claim
  for this layer is "code plus hashes plus a rebuild verified on the author's machine", not
  "rebuild it yourself". One of those intermediates is now closed: `p2-econ` regenerates
  `pairs_unified.csv` byte for byte.
* **`90_capped_build.py`.** The `speed` stage reads three `pairs_slim_cap_*_ALL.parquet` cells that
  this task does not port; they are linked from the legacy tree. Registered in
  `pipeline/NOT_REPRODUCIBLE.md` (entry 9) rather than silently depended on.

Every intermediate named in this section — what produces it, its sha256, and whether it is in the
repo, rebuildable, on the data disk or gone — is tabulated in `pipeline/MANIFEST_intermediates.md`.

---

## 8. cal2026-08-28: the `union-gold` stage (one rung deeper, on demand of the caliber)

The author-signed caliber (2026-08-28) adds chem/math EVENTS, and a new event's dept-channel rows
exist in no frozen artifact — so Task 3 of the caliber rebuild ported the union-frame rung,
`multidisc_gold_2026-08-10/code/10_build_union_frame_gold.py` (gold stage 2/4, whose output is
`p1-gold`'s and `p2-gold`'s input), under the same hunk discipline as its siblings. Its control
run against the frozen inputs, measured 2026-08-28:

| output | verdict |
|---|---|
| `relationships.csv` (both fields) | **byte-identical** to the frozen files |
| `analysis_frame_{field}_2026-08-10.csv` | NOT byte-equal — chemistry 1,066 / 82,995 lines, math 704 / 31,394 lines differ, ONLY in `fwci_frac` / `fwci_frac_ex_star`, worst 4 ULP — hazard H1 reaching this builder's dept-row accumulation loop, the same class §5 documents for `20_rebuild_y_gold.py`. Both columns are REPLACED downstream by `20_rebuild_y_gold.py`'s Y_SWAP, so the noise reaches no frozen frame. |

The caliber run drives this stage (and every other frame stage) over a SHADOW legacy tree via
`$SAR_LEGACY_THESIS` — see `pipeline/stars/caliber_2026-08-28/README.md`. The prodlib rung above
it (`multidisc_prod_2026-07-24/code/`) is NOT ported: the caliber driver stages it verbatim at
run time, sha-pinned, and its control reproduced both frozen `runs/fnfix` network frames
**byte for byte**.
