# Panel 1 robustness battery T1-T4 — 2026-08-29

## What this is

Four checks, all on the canon frames in `data/frames` (the author-approved event set,
116/38/33 — ONE economics set; no batch structure organizes anything here), all local:

- **T1 — leave-one-event-out (LOEO)**: the canon P1 economics union cell fails its joint
  pre-arrival placebo test (p = .0102). For each of the 116 events equally, the union cell
  is re-estimated on the frame minus that event's relations; the ranked table
  (`loeo_ranked.csv`) shows which single removals move the placebo p most and whether the
  ATE moves with them.
- **T2 — missing-output bounds under the thesis's stated fill rule**: the thesis (data and
  strategy sections) states the bounds fill missing output with **zero** and with **the
  person's own average over observed years**. The 2026-08-09 run used the sample mean
  instead — text and computation disagreed. This re-implements the bounds exactly as the
  text states (the exact sentences are quoted in the driver's header) and runs them for
  all three disciplines.
- **T3 — levels**: the strategy section promises the estimates are repeated with output in
  levels (no log transform). Never run before this. `y = fwci_frac` instead of
  `log1p(fwci_frac)`; nothing else changes.
- **T4 — never-exposed comparison pool**: the strategy section promises "the comparison
  pool is restricted to relations of incumbents not yet exposed to any arrival". Never run
  before this. The sentence names no panel; it is implemented for Panel 1 (all three
  disciplines) — the Panel 3 population is fixed pre-arrival by design and its frames
  carry no person ids. Rule: a person-year stays on the comparison side only while the
  incumbent is not yet exposed to ANY arrival (any of their events, any dose, including
  zero); a treated path stays only when its own event is the person's first exposure.
  Switchers whose incumbent was already exposed earlier cannot be classified and
  contribute only their clean early control years (counted in the JSONs).

## Files

- `run_p1_variant.R` — the driver. The prep is a line-for-line copy of the verbatim
  `analysis/estimation/run_p1.R` (untouched), with one clearly-marked insertion per
  variant. Modes: `full <label> <frame> <none|fill0|fillmean|levels|neverexp>` (all three
  channels) and `loeo <label> <frame> <event_id|NONE>` (union channel only). The exact
  thesis sentences each variant implements are quoted in the driver's header.
- `run_all_battery.sh` — the single entry point: two faithfulness controls (`full none`
  and `loeo NONE`, each compare_json-EQUAL to the frozen gold in `analysis/expected/` —
  the proof that the prep is the verbatim prep), then 12 variant cells, then the 116 LOEO
  cells (parallel, `BATTERY_JOBS` processes, default 5), then the ranked summary, then a
  sha256 MANIFEST over `data/robustness_2026-08-29/`.

Both are REPO-AUTHORED and sha-pinned in `tests/test_verbatim_pipeline.py::REPO_AUTHORED`
(refresh with `tools/repin.sh`). The verbatim drivers in `analysis/estimation/` are untouched.

## Cells

| cell | mode/variant | frame | note |
|---|---|---|---|
| P1bnd0_{econ,chemistry,math_stats} | full fill0 | `p1_frame_*.csv` | T2 lower-side fill (zero) |
| P1bndmean_{econ,chemistry,math_stats} | full fillmean | `p1_frame_*.csv` | T2 own-mean fill |
| P1lvl_{econ,chemistry,math_stats} | full levels | `p1_frame_*.csv` | T3 |
| P1nex_{econ,chemistry,math_stats} | full neverexp | `p1_frame_*.csv` | T4 |
| P1loeo_&lt;event&gt; ×116 | loeo | `p1_frame_econ.csv` | T1, union channel only |

Controls in `data/robustness_2026-08-29/control/`: `full/P1_econ_fnfix.json` (whole-JSON
EQUAL) and `loeo/P1_econ_fnfix.json` (EQUAL to the gold's union channel).

## Outputs

`data/robustness_2026-08-29/`: one JSON per cell (verbatim-driver shape plus the variant
bookkeeping keys), `loeo/` (116 JSONs), `loeo_ranked.csv`, `runlog_2026-08-29.log`,
`MANIFEST.sha256`. Results feed the results and robustness sections; the human-readable
summary is a 2026-08-29 results note in the author's manuscript tree (not shipped).
