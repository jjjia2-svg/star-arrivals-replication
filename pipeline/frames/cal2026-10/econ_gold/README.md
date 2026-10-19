# `pipeline/frames/cal2026-10/econ_gold/` — economics through the chem/math gold chain (Piece B)

Repo-authored, 2026-09-22. Reviewed the same day (adversarial review; findings below).
Status: **CONTROL NOT_EQUAL — STOPPED. `--cal` (new inputs) is not implemented. Nothing
downstream may run until the author picks a route (see "Decision needed").**

| file | what |
|---|---|
| `10_build_union_frame_gold_econ.py`, `20_rebuild_y_gold_econ.py`, `30_build_panels23_gold_econ.py` | clones of the three pinned gold builders (`pipeline/frames/multidisc_gold_2026-08-10/code/`), admitting `--field econ`; the only diffs are wiring (`--field` choices, U2 person map, the field's own signed-star table) — listed in `DIFF.md`, asserted by `tests/test_cal2026_10_piece_b.py` |
| `econ_gold_stage.py` | id-shape adapters (`P_` prefix, `star:year` <-> `star:school`), the D4 pool filter (network rows kept only for verified-roster persons), shadow staging names, row-level accounting |
| `run_econ_gold.py` | launcher (declared in `pipeline.lib.paths.LAUNCHERS`): R0 estimator control -> shadow -> three clones in subprocesses -> restore shapes -> R cells -> compare_json -> accounting. Its docstring is the assumption ledger (A1-A7) and carries the control result |
| `DIFF.md` | the three clone diffs against the pinned originals |

Run (control only): `export SAR_OUT_ROOT=/private/tmp/<empty>` then
`setup/.venv/bin/python pipeline/frames/cal2026-10/econ_gold/run_econ_gold.py --control --execute`
(167 s; data disk + legacy tree + R). Products: `data/cal2026-10/econ_gold_control/`
(`control_report.json`, `accounting_P1.json`, `accounting_P2.json`, `estimates/`, `union_frame_econ/`).

## Control result (2026-09-22, review run)

Target: the frozen 2026-09-13 verified-pool cells (`data/robustness_2026-09-13_verified_pool/`),
i.e. the frozen economics P1/P2 frames minus the 162 network-route persons not on the 920 roster.

| check | result |
|---|---|
| R0 estimator positive control (frozen frames -> frozen JSONs) | EQUAL / EQUAL |
| pool filter drops exactly the verified-pool build's 162 persons | yes (162 = 162, sets equal) |
| rows outside the 116-event table | A5044432173's 704 only |
| P1 frame | 103,356 -> 102,795 rows; 70,640 modified (y / dose_topic / age_gap), 561 removed (51 dept-only relations, |age_gap|>60 guard), 0 added; order identical on common keys |
| P2 frame | 157,388 -> 156,614 rows; first ties 349 -> 339 |
| P1 union ATE | -0.368 (SE .062, placebo p .012, obs 81,592) -> **-0.245** (SE .058, placebo p .428, obs 67,827) |
| P1 network / dept ATE | -0.516 -> -0.455 / -0.368 -> -0.300 |
| P2 ATE | +0.305 -> +0.290 |
| verdict | **NOT_EQUAL** |

Determinism: three runs (the last two with hash-seeded children). P2 frame, pairs panel and
all reports byte-identical; the P1 frame differs run to run in `fwci_frac` / `fwci_frac_ex_star`
only (4,804 lines, max 3 ULP) — the pinned union/y builders' known accumulation-order hazard
(`pipeline/NOT_REPRODUCIBLE.md` entry 10; chem/math P1 frames are pinned NOT BYTE-EQUAL for the
same reason). Estimates compare_json-EQUAL across runs.

The differences are the documented definitional ones (A4 y from `u1_edges_full` edges x works with
type exclusion, 18,977 of 62,698 units NA; A5 dose_topic recomputed for the dept builder's rows;
A6 age_gap from `robust_first_pub`), not a defect in the clones. They are large enough to change
the headline economics numbers, so this chain is a **re-definition** of the economics outcome, not
a reproduction of the frozen chain.

## Decision needed (identification layer, not decided here)

The intended design routes economics
through a clone of the legacy `00_build_frame_econ920.py` plus the ported `04_rebuild_y.py` /
`10_panels23_econ920.py` — the chain that produced the frozen frames, whose control can pass.
Piece B took the gold chain instead because the July-only inputs of that chain were listed as
unavailable. Options:

1. **Plan route** — clone `00_build_frame_econ920.py`, keep the ported y/panels builders, add
   only the pool filter (this layer's `econ_gold_stage.pool_ids` / `adapt_network_frame`) and
   Piece A's in-post stage. Needs `u1_full_11school_2026-07-16`, `u3_panel_11school_2026-07-16`,
   `u5_ship_…/output_star1pct.parquet` on the mirror and `econ_fnfix_2026-08-15/u4_aug/star_set`
   + `econ_units_2026-08-09.parquet` in the legacy tree (u3 and star_set present at review time;
   u1_full / u5_ship still syncing).
2. **Gold route for all three fields** — accept the re-definition; then the control target is
   not the frozen economics cells and this NOT_EQUAL is the expected record. The paper's
   economics numbers change beyond what the D1-D7 rules alone imply, and the text would have to
   say so.

## Review findings (2026-09-22)

- The control had never been run to completion (two attempts in the author's scratch: one crashed
  on the `run_frames` dataclass import, the second stopped after the first R cell). Run here: NOT_EQUAL.
- `--cal` was described as "wired"; it is refused unconditionally. Docstring corrected.
- Child interpreters were not hash-seeded (`PYTHONHASHSEED` set inside the child, too late);
  now set on the child's environment.
- The adapter's "no quoting" claim was only a round-trip check; a real `'"' not in line`
  assertion was added (holds on the frozen frame).
- The accounting's row-order flag compared whole lists, so any removed row made it False;
  it now compares the common keys (identical for both frames).
- Supplement source files are now sha256-recorded in the report.
- No tests existed; `tests/test_cal2026_10_piece_b.py` added (clone diff whitelist against the
  pinned shas, event bijection, adapter round trip, pool filter, refusals, no absolute paths).
- Guards: `paths.py` and `run_frames.py` are REPO_AUTHORED (repin-able); their pins and the
  `pipeline_ported.sha256` manifest / `test_paths.py` launcher tuple / `accounted_for` ledger were
  not updated by Pieces A, C, D either — one integration step once every piece has landed.
