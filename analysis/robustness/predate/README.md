# Date-shift (anticipation) test for Panels 2 and 3 — Batch 2, 2026-08-28

## What this is

The estimator's own placebo test is a structural zero for Panels 2 and 3: a relation enters
the comparison for cohort `a` only if it is still unconnected in year `a`, so both the
switcher and the comparison side have recorded no tie in any earlier year and every
pre-arrival coefficient is zero by construction (every P2/P3 log prints "Some placebos could
not be estimated"). The data, however, do carry pre-arrival variation — pairs can and do form
first ties before the star arrives, and they exit the panel at that first tie. Measured on
the frozen frames (2026-08-28 canon): pre-arrival first ties P2 econ/chem/math = 37/20/4,
P3 A_far = 560/136/54, P3 math_stats full pair panel = 503.

The date-shift test uses that variation. Every arrival is shifted two years earlier,
`D' = 1{year >= arrival - 2}`, and the estimation is re-run with everything else identical
(same frozen frames, same estimator arguments, same environment). Horizons k=1 and k=2 of
the shifted run fall on truly pre-arrival years (`arrival-2`, `arrival-1`); under no
anticipation and parallel pre-trends they should be zero. The shifted run's placebos
(`arrival-3` and earlier) also become estimable and are reported as the estimator gives
them. An auxiliary `effects=2` run on the same data provides the joint test of exactly the
two shifted-in horizons (`predate.p_joint_shifted` in the JSONs); per-horizon estimates do
not depend on the `effects` count, so its k=1..2 estimates equal the main run's.

## Files

- `run_predate.R` — the driver. Three modes, each a line-for-line copy of the corresponding
  VERBATIM estimation driver's prep with the single change `D -> D'`:
  `p2` (clone of `analysis/estimation/run_p2.R`; arrival exact from `tau`),
  `p3tp` (clone of `run_p3_tp.R`; arrival = min year with `D==1` per event),
  `p3` (clone of `run_p3.R`; event ids joined from the `_ev` twin frame).
  Every run first proves the arrival reconstruction with a `stopifnot`: `1{year >= arrival}`
  rebuilt from the derived arrival must equal the frozen `D` on every row.
- `run_all_predate.sh` — the single entry point: three shift-0 controls (must be
  compare_json-EQUAL to the frozen golds in `analysis/expected/` — this is the proof that
  the driver's prep is faithful), then the seven locally-runnable shifted cells, then a
  sha256 MANIFEST over `data/predate_2026-08-28/`.

Both are REPO-AUTHORED and sha-pinned in `tests/test_verbatim_pipeline.py::REPO_AUTHORED`
(refresh with `tools/repin.sh`). The verbatim drivers in `analysis/estimation/` are untouched.

## Cells

| cell | mode | frame | note |
|---|---|---|---|
| P2pd2_econ / _chemistry / _math_stats | p2 | `data/frames/p2_becoming_*.csv` | |
| P3pd2_{econ,chemistry,math_stats}_A_far | p3tp | `data/frames/p3_afar_*.parquet` | pair- and event-clustered SEs |
| P3pd2_math_stats_full | p3 | `data/frames/p3_slim_math_stats.parquet` | full pair panel, local per M3 |
| P3 econ / chemistry full pair panels | — | `p3_slim_{econ,chemistry}.parquet` | NOT RUN: would need a 512 GB cloud instance (~$3) |

Controls (shift=0, in `data/predate_2026-08-28/control/`): `P3lb_econ_A_far` (required),
`P2_econ_fnfix` and `P3_fnfix_math_stats` (extra, proving the p2 and p3 preps too).

## Outputs

`data/predate_2026-08-28/`: one JSON per cell (verbatim-driver shape plus, for shifted runs,
`placebos`/`p_joint_placebo` and the `predate` block), `runlog_2026-08-28.log`,
`MANIFEST.sha256`. Results feed the thesis's Section 4.2 anticipation paragraph (Batch 4);
the Section 3 hypothesis-tests paragraph points to them.
