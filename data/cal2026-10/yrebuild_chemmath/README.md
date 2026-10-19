# data/cal2026-10/yrebuild_chemmath — the October y-rebuild reports for chemistry and mathematics

Two small JSON reports (`g_yrebuild_{chemistry,math_stats}.json`) that the October (cal2026-10) Panel 1
build wrote next to the Panel 1 frames it produced. They are the October counterparts of the legacy
`v2_output/multidisc_gold_2026-08-10/data/fnfix/g_yrebuild_{chemistry,math_stats}.json` and carry the
contribution-unit FWCI-missing counts (`fwci_new_na`) for the October incumbent population
(470 chemistry / 481 mathematics persons, field `frame_persons`).

Why they are here: the October chain ran in a temporary working directory
(`<scratch>/chemmath_run2/october_p1_{field}/frames/p1-gold/multidisc_gold_2026-08-10/data/fnfix/`,
the `october.stages.p1.run_dir` of `frames_{field}/build_report_{field}.json`), and only the frames were
frozen. The paper generators need these two reports, so they were copied here unchanged on 2026-09-23
(`cp -p`, bytes pinned in `MANIFEST.sha256`, repo-root-relative keys).

Provenance check done at the copy: the frame written in the same run directory,
`analysis_frame_{field}_new_gold_2026-08-10.csv`, is byte-identical to the frozen frame
(`data/frames/p1_frame_{field}.csv`, `data/cal2026-10/frames_{field}/p1_frame_{field}.csv`):
chemistry sha256 `2fa95c70…fe57d5`, mathematics `47e6f4bb…f771401f9`.

Readers: `analysis/paper/ledger_main.py` (`{chem,math}_yrebuild_keys`) and
`analysis/paper/ledger_carried.py` (`{chem,math}_units_{nofwci,structural,genuine}_pct`).
Never edit these files.
