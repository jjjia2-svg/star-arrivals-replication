# data/robustness_2026-08-29_b — T5 permutation inference + T6 canon sensitivity reruns

2026-08-29, all local, $0, on the canon frames (`data/frames`, event set econ 116 / chem 38 /
math 33). Sibling batch T1–T4 lives in `data/robustness_2026-08-29/` (distinct directory by
design). Estimation everywhere is by the VERBATIM `analysis/estimation` drivers or by the
repo-authored `analysis/robustness/inference/run_perm.R` whose identity draw reproduces the
frozen golds (checked in-driver against `analysis/expected/`).

## Layout

| dir | what | entry point | controls |
|---|---|---|---|
| `perm/` | T5: B=500 event-level timing permutations x 9 headline cells (P1 union / P2 / P3 A_far x 3 disciplines); `perm_summary.{csv,json}` carries the permutation p-values | `bash analysis/robustness/inference/run_all_perm.sh` | 9/9 identity draws EQUAL to the frozen golds (`perm/control/`); seed `config/seeds.yaml: permutation_seed` |
| `afar_event_map/` | proven ev -> event_id maps for the three A_far frames (T6 support) | `analysis/robustness/sensitivity/afar_event_map.py --regen-econ` | rebuilt A_far frames CONTENT-EQUAL to the frozen parquets 3/3; econ pairs regen pinned by becoming_unified byte-equality |
| `departure/` | T6-2: star-departure A/B (2026-08-09 human-verified ledger) on canon, econ P1/P2/P3-A_far; coverage gap over the 37 fnfix events disclosed in the build report | `bash analysis/robustness/sensitivity/run_all_sensitivity.sh` | ledger matches canon 1:1 (arrival + school asserted); no-op line surgery byte-identical |
| `doublestar/` | T6-3: double-star overlap drops (§3's own rule, 5-year window disclosed) — P1/P2/P3-A_far all fields + P3 math full; drop table frozen | same | same surgery control; A_far via the proven maps |
| `nocentre/` | T6-1: ± research-centre rosters (chem/math) rebuilt through the caliber staging machinery on the canon event set; P1/P2 chem+math, P3 math full | same | control build reproduces canon (relationships/becoming BYTE_EQUAL, P1 frames <=3 ULP fwci-only) and run_p1.R on it is compare_json-EQUAL to the golds 2/2 |

Variant frames themselves stay in scratch (`$TMPDIR/sar_*_2026-08-29`) — regenerable in
seconds/minutes from canon by the entry points above; their sha256 are pinned in each build
report. Human-readable results:
the author's private working notes (2026-08-29, T5-T6 results).

## MANIFESTs

- `perm/MANIFEST.sha256` — written by `run_all_perm.sh` at the end of the T5 batch.
- `MANIFEST_t6.sha256` — written by `run_all_sensitivity.sh` over the four T6 dirs.
- `MANIFEST.sha256` (top level) — written last, over everything in this directory.
