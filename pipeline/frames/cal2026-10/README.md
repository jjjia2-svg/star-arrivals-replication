# `pipeline/frames/cal2026-10/` — the October caliber's network-frame rung (Piece A)

Repo-authored, 2026-09-22. Authority: the author's design record of 2026-09-22 (private archive)
(D1 population = roster + two-hop network; D2 network members in post at a sample department in
the arrival year; D3/D4 the verified October roster is the network pool; D5 A5091326353 on his
correct id). Mirrors `pipeline/stars/caliber_2026-08-28/` and imports its `frames_stage.py`
(Shadow, sha pins, prodlib staging) unchanged. Edits no ported file, no legacy file, no frozen
artifact.

| file | what |
|---|---|
| `configs/{chemistry,math_stats,econ}.json` | prodlib configs with path placeholders (`${DERIVED}` = `<ssd_root>/derived`, `${LEGACY_V2}`, `${SHADOW}`, `${RUN_DIR}`). chemistry / math_stats are the frozen fnfix configs (= the 08-28 cal configs) with placeholders; econ is new (u4_frozen events from a derived u4_aug pair, u4_roster_pool on the verified October roster, parquet person map, exclude_list, roster_intervals, works_robust) — the `_cal2026_10_note` keys carry every reason |
| `stage.py` | builds the shadow input tree (frozen links + October tables + derived companions + the econ derived inputs), renders configs, runs the pinned prodlib in process; its docstring is the assumption ledger (incl. the measured A5091326353 person-map facts) |
| `inpost_filter.py` | the D2 stage: drops network rows whose person has no roster spell covering the arrival year; byte-preserving; per-event / per-class build_report |
| `fetch_star_id_supplement.py` | the one live-API step: works of every corrected star id (D5) → `data/cal2026-10/edges_supplement_star_id_corrections_2026-10.jsonl` + request log + works JSON + report |
| `run_cal_frames_chemmath.py` | the chemistry / math_stats frames driver (declared in `LAUNCHERS`): per field, the CONTROL chain without the filter (prodlib BYTE_EQUAL to the 08-28 staged frame -> union-gold -> p1-gold -> p2-gold `--panel3 full` -> make_slim, accepted under the 08-28 freeze rules + run_p1.R / run_p2.R compare_json-EQUAL to analysis/expected), then the OCTOBER chain with `inpost_filter` on the prodlib frame, a row-level accounting of every product against the 08-28 frozen one (named causes only), and the freeze into `data/cal2026-10/frames_<field>/` (+ per-directory MANIFEST.sha256). Measured results in its docstring; sentinel `tests/test_cal2026_10_chemmath.py`. Does not run afar, nothing on AWS |
| `run_controls.py` | C1 / C1e / C2 / C3 controls (+ `--econ-smoke` = E smoke + E2 measurement); measured results in its docstring and in `data/cal2026-10/controls_report_piece_a_review_2026-09-22.json` (current; the 22:04 report predates the exclusion fix and is kept for the record) |

Run: `export SAR_OUT_ROOT=/private/tmp/<empty>` then
`setup/.venv/bin/python pipeline/frames/cal2026-10/run_controls.py --execute --econ-smoke`.

Review 2026-09-22 (adversarial pass on the 22:04 build; recorded in the author's private build log): the econ outcome exclusion
now follows the 08-15 person-level rule (every U2 fragment of a star's person; it had narrowed to
bare ids, leaving 92 fragments / 2,682 works of 21 stars out of the `*_ex_star` outcomes); the
economics prodlib rung gained its byte-level control C1e (frozen 08-15 config, every input
resolved on this machine — the July U4/U5/U0.5 directories ARE on the mirror); two population facts
are written into `stage.py` (the frozen union frame holds 575 relations whose incumbent is an
event-star person, this build 0; the in-post filter's placement is equivalent to a per-event pool
restriction because prodlib's closure restricts only the incumbent end).

Open items for the author (recorded, not decided here): **the economics first-pub rule** — this
config's `works_robust` vs the 08-15 `star_set_academic_age` / `panel_then_wfp` (both runnable: the
U3 panel is on the mirror); E2 measures 13,530 of 26,114 frozen rows changing `age_gap` (1,230 of
2,374 pairs, 11 crossing |60|); the U2 person cluster `P_A5090515599`
merges A5091326353 with a Wenzhou researcher (nil effect inside the event window, see `stage.py`);
the three contaminant works stay in the snapshot edge table (only the supplement drops them).

Chemistry / math_stats frames, 2026-09-23 (`run_cal_frames_chemmath.py`): the October event tables
are byte-identical to the 08-28 tables and the rosters are the frozen ones, so D2 is the only
change. Controls reproduced the 08-28 freeze on both fields (prodlib BYTE_EQUAL on both shadows,
relationships / becoming BYTE_EQUAL, p1 within H1 at worst 4 ULP, pairs / slims content-EQUAL, the
four R cells compare_json-EQUAL). D2 drops 1,778 of 3,153 network relations in chemistry and 391 of
647 in mathematics (no `dropped_no_spell`: the pool is the roster); `both` / `dept_only` relations
are untouched, no row is added, every accounting closes. One mathematics event
(A5074032970:monash) keeps no network row but stays in every frame through its roster channel.
Products: `data/cal2026-10/frames_{chemistry,math_stats}/`; run report
`data/cal2026-10/frames_run_report_chemmath_2026-09-23.json`. The top-level
`data/cal2026-10/MANIFEST.sha256` is NOT regenerated here (the final driver's sweep).

`assemble_frames.py` gathers the per-piece freeze directories into one frames directory under the
data/frames basenames. Every source is a required flag (R1 F3: J0 passes October's directories, J1a
the M stage directories, same code); the economics pairs table must match `--pairs-pin REPORT#KEY`
(sha256 and bytes) before anything is written, else `PAIRS_PIN_MISMATCH`, exit 1. October's values
(`data/cal2026-10/frames/assembly_2026-10.json`), run from the repo root:

Run: `setup/.venv/bin/python pipeline/frames/cal2026-10/assemble_frames.py --execute --econ-dir data/cal2026-10/frames_econ --econ-p1-dir data/cal2026-10/frames_econ --chem-dir data/cal2026-10/frames_chemistry --math-dir data/cal2026-10/frames_math_stats --afar-dir data/cal2026-10/frames_afar --variants-dir data/cal2026-10/frames_variants --pairs-econ output/cal_intermediates/cal2026-10/pairs_unified.csv --pairs-pin data/cal2026-10/frames_econ/build_report_econ920_2026-10.json#october.pairs_unified --out data/cal2026-10/frames`
(`--allow-missing <name> ...` lets named sources be absent; they are listed under `missing` in the record).

## `econ920/` — economics through the CANONICAL econ chain (2026-09-23)

| file | what |
|---|---|
| `00_build_frame_econ920_cal.py` + `DIFF.md` | the path-wired clone of the un-ported legacy union rung (`<legacy>/econ_fnfix_2026-08-15/code/00_build_frame_econ920.py`, sha-pinned; inputs/outputs from a JSON config, 14 lines replaced, no computation line) — generated and `--check`ed by `make_clone.py` |
| `econ920_lib.py` | the network-frame filters (c)/(d) before the clone, (a)/(b) on its output (`postfilter_union`), the shadow, the clone runner (with the G-DOSE population measurement and the evidence-gated override), the row-level proofs, `agg_missing_persons` |
| `run_econ920.py` | the launcher: c1a, gdose, c1b, c2, c3, then the October run (`--override-gdose-gate`); products `data/cal2026-10/frames_econ/`; the controls report goes only to `--controls-report PATH` (a new file, refused if it exists or lies inside data/cal2026-10, data/frames or analysis/expected; required whenever a phase other than `october` runs; R1 F5). `data/cal2026-10/controls_report_econ920_2026-09-23.json` is the frozen record of the 2026-09-23 run; no run writes it |

Run: `export SAR_OUT_ROOT=/private/tmp/<empty>` then
`setup/.venv/bin/python pipeline/frames/cal2026-10/econ920/run_econ920.py --execute --override-gdose-gate --controls-report <new path>`.

Findings written down (details in the two reports): the original union rung is non-deterministic
(edges-fallback float sums in DuckDB scan order; last-bit differences in the y columns 04
overwrites); its G-DOSE gate is a fixed-seed 200-draw that cannot pass on the whole old-relation
population (exact 0.893 < 0.90, 34 of 4,470 relations > 0.01) and passed on 2026-08-13 by draw —
so the person-level filters sit on the clone's output and the October draw's failure is overridden
under an evidence gate, PROVISIONAL until the author rules; `04_rebuild_y.py` exits 2 on 2 October
roster additions (30 old-event rows) outside the frozen units table, so no p1 frame is frozen (the
pre-y frame is). The clone's G-ROW proof: every kept network row byte-identical to the frozen
pre-y frame, 407 network->both channel moves, A5091326353's regenerated event 24 relations after the filters.
