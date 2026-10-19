# Recorded resources of the headline cells

Wall time and maximum resident memory recorded by the AWS cell runner. The numeric values
and source-report hashes are in `resources.json`; the full cell reports are not shipped.
These are measurements of one recorded run, not evidence of a second identical run.

The maximum recorded peak among the four large cells is **210.43 GiB**.
The last column lists capacities above each recorded peak. Leave additional memory for the
operating system and concurrent processes; the listed capacity is not a guarantee of a fit.

| Estimate | R stack | Wall seconds | Peak GiB | Capacities above peak (GiB) |
|---|---|---:|---:|---|
| `P1_econ_fnfix.json` | `rmac` | 42.6 | 6.31 | 16, 32, 64 |
| `P1_fnfix_chemistry.json` | `rmac` | 29.3 | 3.28 | 16, 32, 64 |
| `P1_fnfix_math_stats.json` | `rmac` | 34.6 | 4.45 | 16, 32, 64 |
| `P2_econ_fnfix.json` | `rmac` | 19.2 | 5.8 | 16, 32, 64 |
| `P2_fnfix_chemistry.json` | `rmac` | 13.8 | 2.69 | 16, 32, 64 |
| `P2_fnfix_math_stats.json` | `rmac` | 15.9 | 3.91 | 16, 32, 64 |
| `P3_fnfix_math_stats.json` | `rmac` | 240.1 | 151.57 | above 64 |
| `P3lb_math_stats_A_far.json` | `rmac` | 54.9 | 16.52 | 32, 64 |
| `P3lb_chemistry_A_far.json` | `rmac` | 26.8 | 5.83 | 16, 32, 64 |
| `P3lb_econ_A_far.json` | `rmac` | 124.3 | 39.66 | 64 |
| `P3pos_math_stats_A_far.json` | `rmac` | 167.8 | 56.62 | 64 |
| `P3med_math_stats_A_far.json` | `rmac` | 55.9 | 16.52 | 32, 64 |
| `P3pos_chemistry_A_far.json` | `rmac` | 70.9 | 17.95 | 32, 64 |
| `P3med_chemistry_A_far.json` | `rmac` | 27.4 | 5.84 | 16, 32, 64 |
| `P3pos_econ_A_far.json` | `rmac` | 431.5 | 134.43 | above 64 |
| `P3med_econ_A_far.json` | `rmac` | 120.2 | 39.65 | 64 |
| `P3_fnfix_chemistry.json` | `rcloud` | 86.4 | 59.31 | 64 |
| `P3_econ_fnfix.json` | `rcloud` | 289.3 | 210.43 | above 64 |
| `P1evcl_econ.json` | `rmac` | 37.6 | 6.06 | 16, 32, 64 |
| `P1evcl_chemistry.json` | `rmac` | 27.7 | 3.17 | 16, 32, 64 |
| `P1evcl_math_stats.json` | `rmac` | 32.4 | 4.37 | 16, 32, 64 |
| `P2evcl_econ.json` | `rmac` | 18.7 | 5.8 | 16, 32, 64 |
| `P2evcl_chemistry.json` | `rmac` | 13.2 | 2.66 | 16, 32, 64 |
| `P2evcl_math_stats.json` | `rmac` | 15.5 | 3.66 | 16, 32, 64 |
| `P3evcl_math_stats.json` | `rmac` | 266.2 | 148.11 | above 64 |
| `P3evcl_chemistry.json` | `rcloud` | 102.8 | 58.25 | 64 |
| `P3evcl_econ.json` | `rcloud` | 349.8 | 210.39 | above 64 |
