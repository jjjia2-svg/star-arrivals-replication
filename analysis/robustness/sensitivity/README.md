# analysis/robustness/sensitivity — T6 canon reruns of the three pruned sensitivity checks

The event set changed at the 2026-08-28 caliber freeze (econ 116 / chem 38 / math 33), so the
three §3-promised sensitivity checks that existed only at older calibers had to be re-run
before they can be cited. Design-history-first: each is the OLD design applied unchanged to
the canon frames; where the old record leaves a parameter undefined, the reading is taken
from the paper's own §3 text and disclosed, never invented. Entry point:
`bash analysis/robustness/sensitivity/run_all_sensitivity.sh` (local, needs the data disk for
steps 0 and 3). Estimation is always by the VERBATIM `analysis/estimation` drivers on variant
frames; variant frames live in scratch (regenerable in seconds/minutes from canon), while the
recode tables, accountings, per-file sha256 and estimate JSONs freeze under
`data/robustness_2026-08-29_b/`.

| piece | old design source | what runs on canon | its own control |
|---|---|---|---|
| `afar_event_map.py` | `50_leftbehind_build.py` (ev = DENSE_RANK of event_id in the A_far pair set) | re-derives the A_far selection with the builder's exact SQL and emits ev -> event_id maps for all three fields (econ regenerates the unshipped 663 MB pairs_unified.csv through the caliber shadow + p2-econ) | a map is only written if the rebuilt A_far frame is CONTENT-EQUAL to the frozen parquet (all three passed); the econ regen's becoming_unified must be byte-identical to the shipped canon frame (passed) |
| `build_departure.py` | 2026-08-09 departure A/B (`multidisc_v2_2026-08-04/results/departure_robustness/`, human-verified 25-verdict econ ledger) | A = drop the 17 within-6y departure events; B = treatment off from the verified departure year (22 events); cells P1/P2/P3-A_far econ. **Coverage gap disclosed:** the 37 foreign-poach-fix events postdate the 120-star screen and have no departure verification — they stay "not known to have left" (§3's wording); extending the ledger needs the human verification step (machine signals were shown off by up to 9 years) | all 25 verified stars match canon 1:1 with identical arrival years and schools (asserted); line surgery is byte-preserving with a no-op byte-identity control |
| `build_doublestar.py` | none exists (§3 promise, never run — 2026-08-28 audit found no earlier code); the rule is §3's own sentence | drop e iff an earlier same-department arrival lies within 5 years (§3's Model-1 coverage window, one rule across panels; same-year pairs have no "earlier" member — kept, counted). Drops 98/116 econ, 23/38 chem, 24/33 math. Cells: P1+P2+P3-A_far all fields, P3 full math_stats (pairs_none filter + repo make_slim) | same byte-preserving surgery + the proven A_far maps; the drop table is frozen for review |
| `run_nocentre.py` | 2026-08-10 ± centre rosters (`multidisc_gold_2026-08-10/results/{final,incfel}/out`; the frozen incfel roster IS the old no-centre population) | rebuilds the chem/math frames through the caliber staging machinery (`frames_stage.build_shadow` + the ported builders) with ONE substitution — the roster link pointed at the frozen incfel roster (−134 chem / −28 math centre people); cells P1+P2 chem/math + P3 full math (the old check's coverage; chem P3 is a cloud cell). Economics has no ± variant: its centres were already inside the department rosters by the same 2026-08-10 ruling | control build with the unchanged roster first: relationships + becoming byte-identical to canon, P1 frames within the documented H1 characterisation (<=8 ULP, fwci columns only; measured worst 3), and verbatim run_p1.R on the control frames compare_json-EQUAL to the frozen golds (2/2) — a control failure STOPS the run |

Results and one-line readings are in the author's manuscript tree (a 2026-08-29 results note, not
shipped). No identification interpretation here or there — how each check enters §4.2 is the
author's call.

## 2026-09-10 — the same checks on the CURRENT Panel 3 specification (dose > 0)

The table above was run on the median-cut A_far frames, retired on 2026-08-30. The three
builders now take `--spec {med,pos}` (default `med` = the 2026-08-29 run, byte-for-byte: the
med control re-stages reproduce every 2026-08-29 staged sha256, departure 6/6, doublestar 12/12);
`--spec pos` maps, proves and operates on `data/frames/p3_afar_pos_{field}.parquet` and freezes
under `data/robustness_2026-09-10_p3pos/`. Entry point `run_p3pos_sensitivity.sh`: maps -> departure
A/B (econ) -> double-star (fields whose proven map exists) -> a spec-independence control (the
cut-independent P1/P2 staged files must be byte-identical to the 2026-08-29 stage) -> MANIFEST.
Only Panel 3 A_far cells are estimated (labels `P3depA_pos_econ_A_far`, `P3depB_pos_econ_A_far`,
`P3ds_pos_{field}_A_far`). The econ pos map needs `pairs_unified.csv` regenerated with the data
disk; when it is absent the econ cells are recorded as NOT RUN (`departure/NOT_RUN.md`,
`fields_NOT_built` in the build report) — never inferred from the median map, whose DENSE_RANK
codes belong to a different event set (86 vs 108). `run_nocentre.py` has no pos variant inside it: the
± research-centre check rebuilds the chem/math frames through the caliber staging machinery and
needs the data disk too. Its Panel 3 cell on the pos frames is the separate entry point
`run_nocentre_afar_pos.sh` (-> `run_nocentre_afar_pos.py`, same day): `run_nocentre.build_variant`
verbatim (with-centre control first, then the incfel roster), `build_afar_cut.py` at `pos` with its
`SOURCES` re-pointed at each build's p1 frame / becoming / pairs_none through the explicit
`sources=` parameter added for it (no SQL copied), the verbatim `run_p3_tp.R`. Controls, each a
STOP: the with-centre build reproduces canon (run_nocentre's own checks), its pos A_far frame is
CONTENT-EQUAL to `data/frames/p3_afar_pos_{field}.parquet`, `run_p3_tp.R` on it is compare_json-EQUAL
to `analysis/expected/P3pos_{field}_A_far.json`, and the no-centre relationships/becoming sha256 equal
the 2026-08-29 run's frozen values (so the cell sits on the same frames as the frozen P1nc/P2nc).
Cells `P3nc_pos_{chemistry,math_stats}_A_far` + the control estimates + the report freeze under
`data/robustness_2026-09-10_p3pos/nocentre/`; the frames stay in scratch. Economics: no ± variant.

## 2026-09-23 — the ± research-centre check on the OCTOBER canon (`run_nocentre_cal2026_10.py`)

`run_nocentre.py` and `run_nocentre_afar_pos.sh` stage the 2026-08-28 chain, so after the October
promotion (`data/frames` = cal2026-10, D2 in-post filter) their with-centre control fails and they
stop themselves (recorded in `data/cal2026-10/robustness/sensitivity_report.json` -> `nocentre`). The
October entry point makes the SAME single substitution inside the October chain:
`pipeline/frames/cal2026-10/run_cal_frames_chemmath.py --roster-variant incfel --products-dir <scratch>`
re-points the October shadow's roster link `multidisc_gold_2026-08-10/data/fnfix/roster_gold_<field>.parquet`
at the frozen incfel roster (`data/raw_verified/incfel/`, the 2026-08-10 artifact) and reads the D2
in-post spells from that same file (sha asserted), so prodlib's pool / in-dept index, the union builder's
dept channel / row fill and the D2 filter all see one roster; the control shadow keeps the canon roster.
Controls, each a STOP: (C1) the driver with the unchanged roster reproduces the 08-28 products in its
phase C AND its October products equal the frozen `data/cal2026-10/frames_<field>/`; (C2) the variant
run's own phase C; (C3) the verbatim drivers on the canon October frames compare_json-EQUAL to
`analysis/expected` (P1/P2_fnfix x2, P3_fnfix_math_stats via make_slim, P3cut_pos x2 via
`build_afar_cut.py pos` with explicit sources, its frame content-equal to `data/frames/p3_afar_pos_*`).
The driver's variant accounting names every removed / changed row (person not in the variant roster,
no variant spell at the arrival, channel both<->network/dept_only, in-post row fill, H1). Cells
`P1nc_*`, `P2nc_*`, `P3nc_math_stats_full`, `P3nc_pos_*_A_far` freeze under
`data/cal2026-10/robustness/nocentre/` with `nocentre_report.json`; the variant frames stay in scratch
(sha256 in the report). Economics: no ± variant, as before.

## 2026-10-16 — explicit inputs for the R1 rerun (R1 F3 part 8, F6)

`build_doublestar.py` now names every input by a required flag, with no default and no environment
fallback: `--events-dir` (chemistry/math_stats `events_<f>_cal2026-10.csv`), `--frames-dir`
(`p1_events_ledger_econ.csv`, `p1_frame_<f>.csv`, `p2_becoming_<f>.csv`, the A_far frames) and
`--pairs-none-math` (the table the P3 full maths re-slim filters; it replaces `$SAR_PAIRS_MATH_STATS`,
which is refused if still set). The three callers pass October's values:

    build_doublestar.py ... --events-dir data/cal2026-10 --frames-dir data/frames \
        --pairs-none-math data/cal2026-08-28/frames/pairs_none_math_stats.parquet

The two October event tables are byte-equal to the 08-28 ones the builder read before, so the drop
table stays byte-equal (tests/test_r1_robustness_flags.py rebuilds it).

`afar_event_map.py` keeps its October call unchanged and adds an R1 mode:

    afar_event_map.py --spec pos --frames-dir DIR --pairs-dir DIR --pairs-econ <run>/pairs_unified.csv \
        --outdir OUT --tmpdir TMP [--threads 16 --memory-limit 64GB]

It reads p1/p2/p3_afar_pos of all three fields from `--frames-dir`, the chemistry/math_stats pairs from
`--pairs-dir` and the econ pairs from the run's own chain (never `--regen-econ`). A missing input prints
`AFAR_MAP_STOP missing <path>` and exits 2 before anything is written, and `becoming_unified.csv` beside
the econ pairs must be byte-equal to `DIR/p2_becoming_econ.csv`. Each map is proven by content-equality
with `DIR/p3_afar_pos_<f>.parquet`. `--threads` / `--memory-limit` (defaults 6 / 10GB) set the duckdb
PRAGMAs in both modes. The star-departure builders are unchanged (no departure robustness is printed,
since 2026-10-15).
