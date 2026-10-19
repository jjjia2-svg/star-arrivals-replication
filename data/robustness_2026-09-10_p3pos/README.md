# data/robustness_2026-09-10_p3pos — Panel 3 event-level checks on the dose>0 specification

2026-09-10, local, $0. The departure A/B and double-star cells frozen in
`data/robustness_2026-08-29_b/{departure,doublestar}/` were built on the RETIRED median cut
(A_far events econ 86 / chem 33 / math 31). The paper's Panel 3 since 2026-08-30 is `pos`
(dose > 0; frames `data/frames/p3_afar_pos_{field}.parquet`, events 108 / 38 / 32; golds
`analysis/expected/P3pos_{field}_A_far.json`). This directory holds the SAME two checks
re-staged on the pos frames by the SAME builders (`--spec pos`), estimated by the verbatim
`analysis/estimation/run_p3_tp.R`. Entry point:
`bash analysis/robustness/sensitivity/run_p3pos_sensitivity.sh`. The third frozen check of
2026-08-29, ± research-centre rosters, is re-run on the pos cell under `nocentre/` by its own
entry point `bash analysis/robustness/sensitivity/run_nocentre_afar_pos.sh` (below).

## Layout

| dir | what | control |
|---|---|---|
| `afar_event_map/` | proven ev -> event_id maps for the pos frames, chemistry + math_stats | rebuilt pos frames CONTENT-EQUAL to the frozen parquets (2/2: 184,960 rows / 38 events; 256,506 / 32) |
| `departure/` | **NOT RUN** — see `departure/NOT_RUN.md` | economics-only; no proven econ pos map (below) |
| `doublestar/` | double-star overlap drops (§3's own rule, 5-year window) on the pos frames, chemistry + math_stats; drop table for all three fields; estimates `P3ds_pos_{field}_A_far.json` | line surgery no-op byte-identity; the drop table and the P1/P2 staged files are byte-identical to the 2026-08-29 run (7/7, `SPEC_INDEPENDENCE_OK`) |
| `nocentre/` | ± research-centre check on the pos A_far cell, chemistry + math_stats (economics has no centre variant by design — its centres were inside the department rosters by the 2026-08-10 ruling): `estimates/P3nc_pos_{field}_A_far.json`, `estimates_control/P3cut_pos_{field}.json`, `nocentre_afar_pos_report.json`; frames in scratch (regenerable, ~95 s with the data disk) | with-centre control build reproduces canon (relationships + becoming BYTE_EQUAL, P1 within H1, worst 3 ULP); its pos A_far frame CONTENT-EQUAL to `data/frames/p3_afar_pos_*` (2/2); `run_p3_tp.R` on it compare_json-EQUAL to the golds (2/2); the no-centre relationships/becoming sha256 EQUAL to the 2026-08-29 run's frozen values, its math P3-full slim counts (1,231,888 / 73,119 / 1,283 / 33) and P1 frame rows (39,831 / 23,210) identical to that run |

## What could not be done today, and why

The economics pos map needs `pairs_unified.csv` (643 MB, not shipped). The 2026-08-30 copy
`output/cal_intermediates/pairs_unified.csv` is a dangling symlink into a deleted scratch root,
and regenerating it (`afar_event_map.py --regen-econ`, caliber shadow + stage `p2-econ`) failed
at the stage's own gate: `<openalex_extraction>/derived` is not on this
machine. The median-cut econ map (86 events) is NOT reusable for the pos frame (108 events;
the DENSE_RANK codes differ), so nothing was inferred. Consequently:

- departure A (drop 17 within-6y departures) / B (treatment off from the verified departure
  year, 22 events) on the pos frame: NOT RUN (`P3depA_pos_econ_A_far`, `P3depB_pos_econ_A_far`);
- double-star drops, economics pos: NOT RUN (`P3ds_pos_econ_A_far`).

With the data disk mounted, one re-run of the entry point completes all three cells.

## Results (Panel 3 A_far, pp = the driver's own units, i.e. per-year first-tie hazard)

| cell | frame | ATE | SE pair / event | joint p (pair) | events / pairs / rows / first ties |
|---|---|---|---|---|---|
| main pos (gold) chemistry | pos | −0.00466235 | 0.00296265 / 0.00293027 | .0429 | 38 / 11,466 / 184,960 / 1,004 |
| double-star pos chemistry | pos, 23 events dropped | **−0.00177636** | 0.00164203 / 0.00144332 | .2822 | 15 / 3,096 / 50,209 / 256 |
| double-star med chemistry (2026-08-29) | med, 20 dropped | −0.00769246 | 0.00628522 / 0.00587297 | .3324 | 13 / 638 / 10,286 / 57 |
| main pos (gold) math_stats | pos | +0.00041345 | 0.00041079 / 0.00028871 | .0803 | 32 / 15,318 / 256,506 / 401 |
| double-star pos math_stats | pos, 24 events dropped | **INFEASIBLE** (FAILED_pair / FAILED_event: "infinite or missing values in 'x'") | — | — | 8 / 904 / 15,128 / 27 |
| double-star med math_stats (2026-08-29) | med, 24 dropped | INFEASIBLE | — | — | 7 / 216 / 3,555 / 10 |

Placebos 3–4 could not be estimated in the chemistry cell (no switcher or no control), so the
driver's joint placebo test is absent there, as in the 2026-08-29 run. Descriptive only; how
any of this enters §4.2 is the author's call.

## ± research-centre check on the pos cell (`nocentre/`, 2026-09-10, local, $0)

The 2026-08-29 ± centre run (`data/robustness_2026-08-29_b/nocentre/`) estimated P1, P2 and the P3 FULL
math panel on the frames rebuilt WITHOUT the research-centre academic staff (the frozen incfel roster:
−134 chemistry / −28 math_stats people); it never estimated the paper's Panel 3 cell. This run rebuilds
the same two variants through the same caliber staging machinery (`run_nocentre.build_variant`,
unchanged), cuts the pos A_far cell from each with `build_afar_cut.py` (its `SOURCES` re-pointed by an
explicit `sources=` parameter, no SQL copied) and estimates it with the verbatim `run_p3_tp.R`. The
with-centre build is the control and ran first: its pos frames are CONTENT-EQUAL to the frozen
`data/frames/p3_afar_pos_{chemistry,math_stats}.parquet` and its estimates compare_json-EQUAL to
`analysis/expected/P3pos_*_A_far.json` (`estimates_control/`), so the re-pointing is proven faithful.

| cell | frame | ATE | SE pair / event | joint p (pair) | events / pairs / rows / first ties |
|---|---|---|---|---|---|
| main pos (gold) chemistry | pos, with centres | −0.00466235 | 0.00296265 / 0.00293027 | .0429 | 38 / 11,466 / 184,960 / 1,004 |
| no-centre pos chemistry | pos, incfel roster (−134 centre people) | **−0.00287241** | 0.00216802 / 0.00184767 | .2952 | 36 / 6,655 / 105,694 / 769 |
| main pos (gold) math_stats | pos, with centres | +0.00041345 | 0.00041079 / 0.00028871 | .0803 | 32 / 15,318 / 256,506 / 401 |
| no-centre pos math_stats | pos, incfel roster (−28 centre people) | **+0.00043700** | 0.00040971 / 0.00029681 | .0661 | 32 / 14,509 / 242,872 / 387 |

Chemistry loses two events without the centre people — `A5006982852:monash` and `A5100398634:sydney`
stay in the pair table (38 events) but every A_far-pos pair they had involved a centre person, so the
cell has 36 events; math_stats keeps all 32. The pair count falls 42% in chemistry (11,466 -> 6,655)
and 5% in math_stats (15,318 -> 14,509). Placebos 3–4 are absent in the chemistry cells as in the
gold. Descriptive only; how it enters §4.2 is the author's call. Report:
`nocentre/nocentre_afar_pos_report.json` (every control verdict, counts, sha256 of the variant frames
and of the three inputs each cut read).
