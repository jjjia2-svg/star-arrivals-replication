# `pipeline/stars/caliber_2026-08-28/` — the author-signed caliber layer

> Person names are replaced by OpenAlex author ids in this public copy. An id followed by a year is
> a roster person and an arrival year, not a literature citation; each was verified externally in
> cross-reviewed dossiers that stay in the private archive.

This layer turns the author's 2026-08-28 signing (an internal decision record: D-A `aage >= 2` everywhere, D-B uniform window
`1999 <= arrival_true <= 2024` computed AND consumed everywhere, plus the five personnel rulings)
into the new candidate verdicts and event tables. It is entirely repo-authored, edits **no ported
file and no frozen artifact**, and both calibers stay derivable side by side: the OLD
(signed_2026-08-15) event set is untouched under `data/raw_verified/` and `data/frames/`, the NEW
(cal2026-08-28) set lives under `data/cal2026-08-28/`.

```
export SAR_OUT_ROOT=/private/tmp/<empty dir>          # never inside a cloud-synced folder
python3 "pipeline/stars/caliber_2026-08-28/run_caliber.py" --execute      # ~1 min, needs the data disk
```

## The pieces

| file | what |
|---|---|
| `caliber.py` | the two predicates (`gate_age`, `in_window`) + the OLD caliber's four window paths kept importable |
| `cleaned_works.py` | reader for the cleanup DATA table `data/cal2026-08-28/calls_2026-08-28.csv` — 6 exclusions (A5091826237 −4, A5017222669 −1, A5062352558's 24th call), A5017222669's split-ID merge list (Task-2 fetch, NOT restake drops), and 4 `first_pub_anchor` rows from which first_pub/aage are **computed, never hand-typed** |
| `restake_equiv.py` | the equivalent of the ported `72_restake_fnfix_stars.py`, needed because `72` cannot accept an injected first_pub without editing ported bytes. Everything except the override branch is copied from `72`; the override re-ranks an anchored candidate in the anchored bin by the SAME `+1` convention `72` already uses for its ECON_SF path |
| `run_caliber.py` | the driver (declared in `pipeline.lib.paths.LAUNCHERS`): stages and runs the ported `72` the way `run_stars.py` would, runs the equivalence machine, derives the 71-row verdict set and the three cal event tables, and hard-STOPS on any surprise beyond the expected delta |
| `supplement_fetch.py` | Task 2's live-OpenAlex machinery: the ported `70_prep`'s wire protocol and byte-shaped supplement row, plus a request log `70_prep` never kept, the data-driven cleanup filters, and A5062352558's cache-first sourcing (the frozen 227-work cache supplies membership/year/authors; the live pass supplies only `type` and post-08-15 additions) |
| `run_supplement.py` | the Task-2 driver (in `LAUNCHERS`; runs **no** ported script, so it stages nothing): fetches the five new stars' works + A5017222669's split-ID merge works, applies the cleanups as DATA filters, assembles `edges_supplement_cal2026-08-28.jsonl` on the frozen fnfix bytes, freezes `stars_excluded_cal2026-08-28.parquet` (fnfix 1,832 ∪ the five = 1,837; A5044432173 deliberately NOT added — the star returns to the colleague population under the department-exposure, all-roster rule) and the Task-3 row-level expectations (`colleague_rows_expected_2026-08-28.csv`), and STOPs on any moved profile |

## What the Task-2 fetch measured (run of 2026-08-28, frozen in `data/cal2026-08-28/`)

* 14 live API requests, ~24 s, request log frozen (`api_request_log_2026-08-28.jsonl`, no key).
* Works fetched → supplement rows after the signed cleanups: A5027778630 633→633 · A5091826237 878→**874**
  (−4 contaminants) · A5017222669 144→**147** (−1 contaminant, +4 merge works) · A5090916445 125→125 ·
  A5062352558 cache 227→**226** (−W2002298104, the 24th call).
* Profile totals matched the dossiers' 08-27 measures exactly (A5027778630 633, A5091826237 878, A5090916445 125);
  A5017222669's four A5083852619 merge works were all present with citation counts **identical** to the
  dossier's (5118/681/1309/15 — 7,123 citations recovered), each still held by the split profile.
* A5062352558's live profile (227 works) matched the frozen cache id-for-id — zero drift, zero field
  diffs; the completeness report's "+1 2025 work (228)" did not appear in the works listing and is
  recorded in the task report, inside tolerance.
* Colleague-side rows the five vacate (frozen frames, for Task 3's accounting): p1 220/198/187/55/22
  and p2 340/306/289/85/34 (= 11×/17× their relation rows 20/18/17/5/2); pair-layer rows in the
  legacy fnfix intermediates 43,475/39,250/39,586/6,169/2,499. A5044432173: star-side p1 1,012 / p2 1,547
  leave with that event; colleague-side p1 88 / p2 136 persist (roster melbourne_econ 2007–2011,
  human-verified).

## What the machine said (run of 2026-08-28, frozen in `data/cal2026-08-28/`)

* **Equivalence proof (E1)**: the caliber machine, on the frozen 67-row inputs with no overrides,
  reproduced the frozen `fnfix_restake_2026-08-15.csv` rows **byte for byte, 5/5** (A5018518935, A5006190609,
  A5035138469, A5074090421 — all untouched by the 2026-08-28 cleanups — plus A5062352558). Pinned in
  `tests/test_caliber_2026_08_28.py`. **Scope**: E1 exercises only the shared `72` code path — no
  frozen row uses the override branch, so the 5/5 cannot reach it. The anchored-bin path is
  validated separately: E2's cross-check (every non-override field byte-equal to the ported
  machine's output; A5091826237's row the sole, documented divergence) and the T1 review's independent
  SQL re-derivation of all 71 verdict rows, A5091826237's .9122 included.
* **Ported `72` (phase P)**, driven on the 4 admissions + A5062352558 with the calls table = frozen 374
  drops + the 6 signed exclusions (380): A5027778630 .9981 / A5091826237 .9201 (native bin) / A5017222669 .9643 /
  A5090916445 .9057, and A5062352558's row **byte-identical to the frozen row** — measured proof that the
  24th call (W2002298104, a 2003 work) is zero-effect at Y=2002.
* **A5091826237 (register ruling 2, machine-conditional)**: none of the 4 contaminants carries snapshot
  citations (stock 321 unchanged — the dossier's "0% if not in the snapshot" branch), the anchored
  first_pub=1983 moves the candidate to bin `1605|14-17` (cell_n 3521), and the re-rank returns
  **pct .9122 ≥ .90 → PASS**. The native-bin row (`1605|10-13`, cell_n 4317, .9201) is pinned
  beside it in `restake_ported72_newcands_2026-08-28.csv`.
* **A5017222669**: dropping the 1992 contaminant moved the machine's own rfp to 1993 → aage 8, same
  6-9 bin, pct .9643 unchanged — the anchored value and the machine-native value coincide
  (dossier B-1 confirmed by the machine).

## The event delta (OLD signed_2026-08-15 → NEW cal2026-08-28)

| discipline | old | new | change |
|---|---|---|---|
| econ | 117 | **116** | −1: A5044432173 out (D-A, aage=0 — the F1 defect corrected) |
| chemistry | 35 | **38** | +3 in: A5027778630 arr. 2002, A5091826237 arr. 2001 machine pass, A5062352558 arr. 2003 D-B |
| math_stats | 31 | **33** | +2 in: A5017222669 arr. 2002, A5090916445 arr. 2002 |

The candidate-level diff on the frozen 67 is exactly {A5044432173 out, A5062352558 in} — asserted by the driver
(any other flip is a STOP) and pinned by the tests. Every event in every cal table satisfies the
uniform window.

## Findings kept visible, not repaired

* `72`'s `pass_p10` still omits gate ② (F1): A5044432173's row in `restake_2026-08-28.csv` still says
  `after_pass=True, aage=0`. D-A lives in `caliber.gate_age`, applied in the verdict layer, so the
  machine's output remains what the ported code wrote.
* The 4-dp rounding (F2) and the float/exact split (F3) are inherited unchanged by
  `restake_equiv.py` — fidelity to `72` outranks tidiness here by design.
* The frozen candidates table's `in_window` column is the LEGACY flag; the cal layer recomputes
  the window from `arrival_true` everywhere and never consumes that column.

## Task 3 — the frames rebuild (frames_stage.py / cal_accounting.py / run_cal_frames.py)

The T3 driver rebuilds every frame under the caliber through the PORTED builders (verbatim):

* **The shadow legacy tree.** The builders resolve their inputs through `legacy_thesis()`, which
  honours `$SAR_LEGACY_THESIS` (the T8 run_fwci arrangement). `frames_stage.build_shadow` links
  the frozen inputs, stages the cal event tables / supplement / exclusions at the exact fnfix
  names the builders resolve, derives the 70_prep companions (fnfixbase, shortlist), and records
  every entry in `frames/staging_manifest_2026-08-28.json`.
* **The one new port**: `pipeline/frames/multidisc_gold_2026-08-10/code/10_build_union_frame_gold.py`
  (the union-frame rung the new events force; run_frames stage `union-gold`), path hunks only,
  proved by the verbatim suite. `prodlib` (`multidisc_prod_2026-07-24/code/`) is NOT ported: it is
  staged verbatim at run time, sha-asserted against `frames_stage.PINNED_LEGACY_CODE`, with the
  unit modules it imports pre-imported from this repo's ported copies (origin-asserted).
* **Econ surgery**: econ has no new events, so the two un-ported econ rungs'
  cal inputs are their frozen outputs minus event `A5044432173:2006`'s rows, byte-preserving
  every other line; the ported 01/04/split/10/make_slim/50 then run for real, and the row-level
  accounting (strict removal walks) is the proof the surgery claims nothing it did not do.
* **Controls before cal**: prodlib must reproduce the frozen `runs/fnfix` frames byte for byte
  (measured: BYTE_EQUAL, both fields); the union builder must reproduce the frozen union frames
  up to the documented H1 class (measured: relationships.csv byte-identical, frame differs only
  in fwci_frac/fwci_frac_ex_star at ≤4 ULP).
* **The accounting** (`cal_accounting.py`): every row in/out/changed attributed to a named cause
  (`A5044432173_event`, `five_member`, `new_event`, `h1_fwci_ulp`, `ex_star_ripple`, `coauthor_ripple`);
  T2's pinned expectations evaluated verbatim — **the chem/math colleague-side pins DEVIATE by
  design of the machinery** (dept-channel colleague seats persist under the rule that
  other stars may count as colleagues; only the network channel leaves via stars_excluded), and that deviation
  is recorded as an OPEN item, never absorbed. Products land in
  `data/cal2026-08-28/frames/` with the same basenames as `data/frames/` (the directory carries
  the caliber; econ's split is honestly `p1_frame_econ_new37.csv`).

## Task 4 — local estimation + old-vs-new comparison (run_cal_estimates.py)

The T4 driver (in `LAUNCHERS`; runs NO ported python) estimates every locally runnable cell on
`data/cal2026-08-28/frames/` through the VERBATIM R drivers in `analysis/estimation/` (their own
argv + `$SAR_OUT` contract, `$SAR_OUT` under an out-of-repo `$SAR_OUT_ROOT`):

* **19 local cells** (5×P1 incl. old79/new37, 3×P2, math P3, 3×P1evcl, 3×P2evcl, math P3evcl,
  3×A_far), sequentially, per-cell logs; the evcl self-check refs are the CAL person/pair-cluster
  results from the same run (same frame, other cluster). The econ P1 cell runs TWICE — the two
  results must be compare_json-EQUAL (determinism). `P1_econ_fnfix_old79` (byte-identical frame,
  T3) must be compare_json-EQUAL to the frozen gold — the estimator-environment positive control.
* **4 cloud cells registered for Task 5** (`P3_econ_fnfix`, `P3_fnfix_chemistry`, `P3evcl_econ`,
  `P3evcl_chemistry` — `tools/compare_all.py` CLOUD_ONLY), with their cal payload parquets +
  sha256s. Together with the local inventory this partitions the 23 frozen expected cells exactly
  (pinned in `tests/test_cal_estimates_2026_08_28.py`).
* Products: `data/cal2026-08-28/estimates/` (result JSONs in the `analysis/expected/` shape +
  the determinism re-run + the run report; MANIFEST regenerated, pure addition) and the generated
  comparison table (an internal review document, not published) (ATE + per-effect tables,
  sign/significance/|dATE|>20% flags; no interpretation). A cell error is STOPPED and reported —
  never patched; any stop freezes nothing.

## Task 5 — the four cloud cells (run_cal_cloud.py)

* The four CLOUD_ONLY estimation cells (`P3_fnfix_chemistry`, `P3_econ_fnfix`,
  `P3evcl_chemistry`, `P3evcl_econ` — the T4 registry, which is authoritative over the plan's
  "chem P3 A_far" phrase, T4-review MINOR-1) ran ONCE on a rented 512 GB `r6i.16xlarge`
  (us-east-1, the `pipeline/aws/` runbook recipe: same AMI, same r2u+rustup bootstrap, ten-hour
  shutdown fuse, salvage-before-terminate watcher).
* `run_cal_cloud.py` is the LOCAL custody half: `--preflight` three-way sha-verifies the
  payloads (disk == cal MANIFEST == T4 registry) and writes the shipping bundle
  (`data/cal2026-08-28/cloud/payload.md5`, `bootstrap.sh`, `driver.sh`, `userdata.txt`) plus the
  runbook-based cost estimate BEFORE anything is uploaded; `--verify` closes the chain after the
  fetch (frames on disk == payload.md5 == the instance's own `md5sum -c` OK lines tee'd into
  driver.log; ALL_DONE marker; four zero exits; evcl point estimates == their mains to the
  JSON's 8 digits) and writes `cloud/custody_2026-08-28.json` (instance id, timestamps, billed
  minutes, actual cost, per-cell payload-hash-before / result-hash-after); `--freeze` byte-copies
  the four JSONs into `estimates/`, extends the comparison doc through Task 4's own
  `rows_for`/`flags_for`, and regenerates the cal MANIFEST with a pure-addition assertion.
  It contains NO aws/ssh invocation — the money-spending commands are the operator's, recorded
  in `cloud/watcher.log` (the `pipeline/aws/` print-only discipline).
* The M1 "cloud estimator version not verified" register gap is closed for the cal run: the instance
  writes `versions.txt` (R, DIDmultiplegtDYN, polars, data.table, jsonlite, apt line, uname) and
  it is fetched with the results.

## Task 6 — the caliber ledger + the author report (run_cal_ledger.py) — STOP POINT

* `run_cal_ledger.py` derives the caliber Panel-3 (A_far) ledger by running the UNEDITED
  `analysis/paper/ledger_p3afar.py` in this process (runpy, inside a `staged_run` mark) with
  `load_paths()` pointed at the cal universe: estimates → `data/cal2026-08-28/estimates/`,
  frames → a scratch shadow holding the cal A_far panels + counts table (sha-verified against
  the cal MANIFEST before staging), legacy tree and `data/paper_inputs` → empty scratch dirs so
  neither the legacy cross-check nor the OLD no-effect simulations can leak old-caliber numbers
  in. The speed bracket is staged HEADER-ONLY: its cap-cell inputs have no builder anywhere
  (`pipeline/NOT_REPRODUCIBLE.md` entry 9), so the cal ledger honestly omits `speed_bracket`
  (and `null_simulation` — `B0_null_test.R` is not in this repository).
* The generator runs TWICE ($SOURCE_DATE_EPOCH=0); the two ledgers and the two figures must be
  byte-identical. Products: `data/cal2026-08-28/data_numbers_cal_p3afar.json` (the produced
  ledger plus one added `_cal_note` key declaring the true cal provenance),
  `fig_p3_afar_cal.pdf`, `ledger_run_report_2026-08-28.json`; cal MANIFEST regenerated with a
  pure-addition assertion. `tests/test_cal_ledger_2026_08_28.py` re-derives every ledger
  quantity from the cal estimate JSONs / counts table and the raw rates with independent SQL.
* The author report: an internal results note (not published). **The plan ENDS there** — thesis edits, re-freezing
  `data/frames`/`analysis/expected`, and the sentinel update all await the author's approval.
