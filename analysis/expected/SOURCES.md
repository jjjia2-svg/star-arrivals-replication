# Recorded estimates of the October 2026 version — where each file came from

These 29 files are the recorded estimates of the October 2026 version of the data (184 events), which
`config/paths_october.yaml` selects. The recorded estimates of the report as submitted are in
`data/report/expected/`.

| file | source |
|---|---|
| P1_econ_fnfix.json | `data/cal2026-10/estimates/P1_econ_fnfix.json` |
| P1_fnfix_chemistry.json | `data/cal2026-10/estimates/P1_fnfix_chemistry.json` |
| P1_fnfix_math_stats.json | `data/cal2026-10/estimates/P1_fnfix_math_stats.json` |
| P1_econ_fnfix_old79.json | `data/cal2026-10/estimates/P1_econ_fnfix_old79.json` |
| P1_econ_fnfix_new37.json | `data/cal2026-10/estimates/P1_econ_fnfix_new37.json` |
| P2_econ_fnfix.json | `data/cal2026-10/estimates/P2_econ_fnfix.json` |
| P2_fnfix_chemistry.json | `data/cal2026-10/estimates/P2_fnfix_chemistry.json` |
| P2_fnfix_math_stats.json | `data/cal2026-10/estimates/P2_fnfix_math_stats.json` |
| P3_fnfix_math_stats.json | `data/cal2026-10/estimates/P3_fnfix_math_stats.json` |
| P1evcl_econ.json | `data/cal2026-10/estimates/P1evcl_econ.json` |
| P1evcl_chemistry.json | `data/cal2026-10/estimates/P1evcl_chemistry.json` |
| P1evcl_math_stats.json | `data/cal2026-10/estimates/P1evcl_math_stats.json` |
| P2evcl_econ.json | `data/cal2026-10/estimates/P2evcl_econ.json` |
| P2evcl_chemistry.json | `data/cal2026-10/estimates/P2evcl_chemistry.json` |
| P2evcl_math_stats.json | `data/cal2026-10/estimates/P2evcl_math_stats.json` |
| P3evcl_math_stats.json | `data/cal2026-10/estimates/P3evcl_math_stats.json` |
| P3lb_econ_A_far.json | `data/cal2026-10/estimates/P3lb_econ_A_far.json` |
| P3lb_chemistry_A_far.json | `data/cal2026-10/estimates/P3lb_chemistry_A_far.json` |
| P3lb_math_stats_A_far.json | `data/cal2026-10/estimates/P3lb_math_stats_A_far.json` |
| P3pos_math_stats_A_far.json | `data/cal2026-10/estimates/P3pos_math_stats_A_far.json` |
| P3med_math_stats_A_far.json | `data/cal2026-10/estimates/P3med_math_stats_A_far.json` |
| P3pos_chemistry_A_far.json | `data/cal2026-10/estimates/P3pos_chemistry_A_far.json` |
| P3med_chemistry_A_far.json | `data/cal2026-10/estimates/P3med_chemistry_A_far.json` |
| P3pos_econ_A_far.json | `data/cal2026-10/estimates/P3pos_econ_A_far.json` |
| P3med_econ_A_far.json | `data/cal2026-10/estimates/P3med_econ_A_far.json` |
| P3_econ_fnfix.json | `data/cal2026-10/cloud/fetch/out/P3_econ_fnfix.json` |
| P3_fnfix_chemistry.json | `data/cal2026-10/cloud/fetch/out/P3_fnfix_chemistry.json` |
| P3evcl_econ.json | `data/cal2026-10/cloud/fetch/out/P3evcl_econ.json` |
| P3evcl_chemistry.json | `data/cal2026-10/cloud/fetch/out/P3evcl_chemistry.json` |

P3pos_*/P3med_* (six files) are the Panel 3 cells on the dose-above-zero cut (`pos`, the report's
Panel 3) and on the former median cut (`med`, a control equal to P3lb_* except its label). They were
first frozen from `data/robustness_afar_cuts_2026-08-30/estimates/` and re-estimated on the October
data with the other cells. The four large cells come from the October cloud run
(`data/cal2026-10/cloud/`). Never edit these files; compare new runs against them.
