# data/frames

Analysis-layer inputs for the P1 (levels), P2 (becoming), and P3 (event-study /
A_far) estimators, across the three fields (economics, chemistry, math/stats):
the unified analysis frames, the two economics Panel 1 sensitivity frames
(`p1_frame_econ_old79.csv`, `p1_frame_econ_new37.csv`), the becoming panels, the
slim P3 pairs shipped to EC2, the event-clustered P3 pairs, the A_far robustness
pairs, the A_far counts/speed-bracket/tau-profile tables, and the economics event
ledger.

**Canon since 2026-09-23 (cal2026-10, the October caliber).** Every frame here is a byte copy of its counterpart in `data/cal2026-10/frames/` (assembled by `pipeline/frames/cal2026-10/assemble_frames.py` from the per-discipline freezes `frames_econ/`, `frames_chemistry/`, `frames_math_stats/`, the Panel 3 sweep `frames_afar/` and the D7 variants `frames_variants/`; provenance and controls in their reports and `tests/test_cal2026_10_*.py`, `tests/test_cal_afar_2026_10.py`, `tests/test_p3_full_variants_2026_10.py`). Design: the author's design record of 2026-09-22 (private archive) (D1-D8). New files: `p3_slim_<field>_{p05,dosebin3}.parquet` (D7), `relationships_econ.csv`, `pairs_none_{chemistry,math_stats}.parquet`. The 2026-08-28 canon below is one directory away (`data/cal2026-08-28/frames/`) and at tag `cal-2026-08-28`.

**Canon since the 2026-08-28 freeze (author approved the caliber rebuild; the decision record is kept in the
author's private archive).** Every frame here except
`p3_afar_speed_bracket.csv` is a byte copy of its counterpart in
`data/cal2026-08-28/frames/` — the caliber rebuild's frozen output (econ 116
events: A5044432173 removed; chemistry 38: +A5027778630, +A5091826237,
+A5062352558; math-stats 33: +A5017222669, +A5090916445). Their provenance chain (staging manifest, run report,
row-level accounting, controls) lives in that directory and is pinned by
`tests/test_cal_frames_2026_08_28.py`; `tools/import_frozen.py` carries the
exact per-file mapping and `data/MANIFEST.sha256` the hashes. Never edit them
here.

**Public copy.** `data/cal2026-08-28/frames/` is published in full (the frozen 28 August 2026
canon, which the custody check of the four cloud cells reads), as is `data/cal2026-10/frames/`
(the October assembly this directory is a byte copy of). In `p1_events_ledger_econ.csv` (here,
in `data/cal2026-10/frames/`, `frames_econ/` and `data/cal2026-08-28/frames/`) the evidence URLs
in `evidence_source` were blanked. Here, in `data/cal2026-10/frames/` and in `frames_econ/`,
`reason` and `evidence_source` also hold fixed English codes (the private notes were in Chinese or
named an input that is not shipped): `STAGE_A_zero_coupling` = no candidate coauthor pair before
arrival; `STAGE_B_one_per_person` = the frame's one candidate incumbent is assigned to another
event; `STAGE_A_dose_tier` = not in a dose tier of the p01 main frame; `added_2026-10` = a row
added from the signed 2026-10 add list, where present. Every public copy carries these codes, with
or without `data/report/`: the October 2026 version was not published before, and this release
ships it in English. No estimator reads either column.

`p1_frame_econ_old79.csv` is byte-identical on both sides of the freeze
(none of its 79 events moved). The pre-caliber frames are one checkout away at
tag `pre-cal-freeze`.

`p3_afar_speed_bracket.csv` is the ONE exception: it has no cal builder (its
capped cells' producer `90_capped_build.py` is not ported) and still reflects
the PRE-caliber event set — see `pipeline/NOT_REPRODUCIBLE.md` (index row 9 and
the speed-bracket entry) — pending the freeze-wave Task-8 paper decision.

`p1_frame_econ_old79.csv` and `p1_frame_econ_new37.csv` are two economics
Panel 1 sensitivity frames: the first restricted to the 79 pre-existing
arrival events, the second to the 37 events added by the foreign-poach
false-negative fix that survive the 2026-08-28 caliber (the fix's 38th,
A5044432173, was removed by the author-signed caliber decision; the frame is
honestly named `new37`, and the pre-caliber `new38` frame is at tag
`pre-cal-freeze`).

Rebuilding these frames goes through the caliber staging layer
(`pipeline/stars/caliber_2026-08-28/run_cal_frames.py`, driving the verbatim
ported builders over the cal event tables/supplement), which is also what the
acceptance proof in `tests/test_pipeline_rebuild.py` (`-k t7`) now drives; it
needs the read-only legacy trees and the data disk. The chem/math cal pair
tables are shipped (`data/cal2026-08-28/frames/pairs_none_*.parquet`); the econ
cal `pairs_unified.csv` (663 MB) is not shipped and regenerates in ~24 s
(stage `p2-econ`; sha pinned in the frames run report).
`analysis/run_all.sh` uses the frozen files directly.
