# R1 M golds — where each file came from

Written by pipeline/aws/r1/promote_r1.py (J1a stage `promote`). Each file is a byte copy of the cell output the J1a cells stages just ran (run_cells.py on config/r1/cells/M.tsv and M_evcl.tsv against the assembled M frames). October's golds (analysis/expected) are untouched; expected_refreeze_r1.json lists the October and new sha256 of every gold and frame. Moving these into analysis/expected is the author's call after P5.

| file | cell | stack | driver | frame | ref | source |
|---|---|---|---|---|---|---|
| P1_econ_fnfix.json | P1_econ_fnfix | rmac | `analysis/estimation/run_p1.R` | p1_frame_econ.csv | - | `/work/prod/estimates_M/P1_econ_fnfix.json` |
| P1_fnfix_chemistry.json | P1_fnfix_chemistry | rmac | `analysis/estimation/run_p1.R` | p1_frame_chemistry.csv | - | `/work/prod/estimates_M/P1_fnfix_chemistry.json` |
| P1_fnfix_math_stats.json | P1_fnfix_math_stats | rmac | `analysis/estimation/run_p1.R` | p1_frame_math_stats.csv | - | `/work/prod/estimates_M/P1_fnfix_math_stats.json` |
| P2_econ_fnfix.json | P2_econ_fnfix | rmac | `analysis/estimation/run_p2.R` | p2_becoming_econ.csv | - | `/work/prod/estimates_M/P2_econ_fnfix.json` |
| P2_fnfix_chemistry.json | P2_fnfix_chemistry | rmac | `analysis/estimation/run_p2.R` | p2_becoming_chemistry.csv | - | `/work/prod/estimates_M/P2_fnfix_chemistry.json` |
| P2_fnfix_math_stats.json | P2_fnfix_math_stats | rmac | `analysis/estimation/run_p2.R` | p2_becoming_math_stats.csv | - | `/work/prod/estimates_M/P2_fnfix_math_stats.json` |
| P3_fnfix_math_stats.json | P3_fnfix_math_stats | rmac | `analysis/estimation/run_p3.R` | p3_slim_math_stats.parquet | - | `/work/prod/estimates_M/P3_fnfix_math_stats.json` |
| P3lb_math_stats_A_far.json | P3lb_math_stats_A_far | rmac | `analysis/estimation/run_p3_tp.R` | p3_afar_math_stats.parquet | - | `/work/prod/estimates_M/P3lb_math_stats_A_far.json` |
| P3lb_chemistry_A_far.json | P3lb_chemistry_A_far | rmac | `analysis/estimation/run_p3_tp.R` | p3_afar_chemistry.parquet | - | `/work/prod/estimates_M/P3lb_chemistry_A_far.json` |
| P3lb_econ_A_far.json | P3lb_econ_A_far | rmac | `analysis/estimation/run_p3_tp.R` | p3_afar_econ.parquet | - | `/work/prod/estimates_M/P3lb_econ_A_far.json` |
| P3pos_math_stats_A_far.json | P3cut_pos_math_stats | rmac | `analysis/estimation/run_p3_tp.R` | p3_afar_pos_math_stats.parquet | - | `/work/prod/estimates_M/P3pos_math_stats_A_far.json` |
| P3med_math_stats_A_far.json | P3cut_med_math_stats | rmac | `analysis/estimation/run_p3_tp.R` | p3_afar_med_math_stats.parquet | - | `/work/prod/estimates_M/P3med_math_stats_A_far.json` |
| P3pos_chemistry_A_far.json | P3cut_pos_chemistry | rmac | `analysis/estimation/run_p3_tp.R` | p3_afar_pos_chemistry.parquet | - | `/work/prod/estimates_M/P3pos_chemistry_A_far.json` |
| P3med_chemistry_A_far.json | P3cut_med_chemistry | rmac | `analysis/estimation/run_p3_tp.R` | p3_afar_med_chemistry.parquet | - | `/work/prod/estimates_M/P3med_chemistry_A_far.json` |
| P3pos_econ_A_far.json | P3cut_pos_econ | rmac | `analysis/estimation/run_p3_tp.R` | p3_afar_pos_econ.parquet | - | `/work/prod/estimates_M/P3pos_econ_A_far.json` |
| P3med_econ_A_far.json | P3cut_med_econ | rmac | `analysis/estimation/run_p3_tp.R` | p3_afar_med_econ.parquet | - | `/work/prod/estimates_M/P3med_econ_A_far.json` |
| P3_fnfix_chemistry.json | P3_fnfix_chemistry | rcloud | `analysis/estimation/run_p3.R` | p3_slim_chemistry.parquet | - | `/work/prod/estimates_M/P3_fnfix_chemistry.json` |
| P3_econ_fnfix.json | P3_econ_fnfix | rcloud | `analysis/estimation/run_p3.R` | p3_slim_econ.parquet | - | `/work/prod/estimates_M/P3_econ_fnfix.json` |
| P1evcl_econ.json | P1evcl_econ | rmac | `analysis/estimation/run_p1_evcl.R` | p1_frame_econ.csv | P1_econ_fnfix.json | `/work/prod/estimates_M/P1evcl_econ.json` |
| P1evcl_chemistry.json | P1evcl_chemistry | rmac | `analysis/estimation/run_p1_evcl.R` | p1_frame_chemistry.csv | P1_fnfix_chemistry.json | `/work/prod/estimates_M/P1evcl_chemistry.json` |
| P1evcl_math_stats.json | P1evcl_math_stats | rmac | `analysis/estimation/run_p1_evcl.R` | p1_frame_math_stats.csv | P1_fnfix_math_stats.json | `/work/prod/estimates_M/P1evcl_math_stats.json` |
| P2evcl_econ.json | P2evcl_econ | rmac | `analysis/estimation/run_p2_evcl.R` | p2_becoming_econ.csv | P2_econ_fnfix.json | `/work/prod/estimates_M/P2evcl_econ.json` |
| P2evcl_chemistry.json | P2evcl_chemistry | rmac | `analysis/estimation/run_p2_evcl.R` | p2_becoming_chemistry.csv | P2_fnfix_chemistry.json | `/work/prod/estimates_M/P2evcl_chemistry.json` |
| P2evcl_math_stats.json | P2evcl_math_stats | rmac | `analysis/estimation/run_p2_evcl.R` | p2_becoming_math_stats.csv | P2_fnfix_math_stats.json | `/work/prod/estimates_M/P2evcl_math_stats.json` |
| P3evcl_math_stats.json | P3evcl_math_stats | rmac | `analysis/estimation/run_p3_evcl.R` | p3_slim_ev_math_stats.parquet | P3_fnfix_math_stats.json | `/work/prod/estimates_M/P3evcl_math_stats.json` |
| P3evcl_chemistry.json | P3evcl_chemistry | rcloud | `analysis/estimation/run_p3_evcl.R` | p3_slim_ev_chemistry.parquet | P3_fnfix_chemistry.json | `/work/prod/estimates_M/P3evcl_chemistry.json` |
| P3evcl_econ.json | P3evcl_econ | rcloud | `analysis/estimation/run_p3_evcl.R` | p3_slim_ev_econ.parquet | P3_econ_fnfix.json | `/work/prod/estimates_M/P3evcl_econ.json` |
