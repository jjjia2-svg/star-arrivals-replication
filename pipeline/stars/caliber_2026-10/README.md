# `pipeline/stars/caliber_2026-10/` — the October 2026 caliber (star layer)

Author decisions of 2026-09-22 (the author's design record of 2026-09-22 (private archive)):
D5 re-verify the flagged economics stars paper by paper and correct A5091326353's id; events whose
star falls below the top-10% cut after cleaning are dropped. D7 a top-5% star subset for robustness.

| file | what |
|---|---|
| `build_calls.py` | assembles `data/cal2026-10/calls_2026-10.csv` (schema of `calls_2026-08-28.csv`): the 14 rows of 2026-08-28 carried forward + every `is_mine=false` call of the 2026-09-22 recheck (`data/star_recheck_2026-09-22/`, 17 stars, two-round LLM adjudication; not shipped: per-paper records with names, restricted deposit) as `exclude`, split-id works as `merge_from_<id>` (fetch merges, never restake adds — the 08-28 policy). Also `star_id_corrections_2026-10.csv` (A5090515599 → A5091326353). |
| `run_caliber.py` | reads the 187-row departure-verification ledger (`data/departure_verification_2026-09-10/`, not shipped: restricted deposit); re-ranks ALL 187 event stars with the multidisc machine (`restake_equiv`, i.e. `72`'s `_POOL_SQL`) on `u1_edges_full_2026-07-05`; controls E1 (71 candidates of 08-28, byte-identical) and E2 (42 original chem/math stars, pct equal to the 08-13 table). Writes verdicts, event tables, `pass_p05`. |
| `restake_econ11.py` | the SAME machine on `u1_full_11school_2026-07-16` for economics, with the July percentiles as control (see finding below). |

## Finding 2026-09-22: two extractions, one machine

Run 2 of `run_caliber.py` (E1 71/71, E2 42/42 both pass) dropped 44 of 116 economics events —
22 `not_in_pool`, the rest understated. Cause, verified on the data disk: the July economics
stars were ranked on the 11-school extraction `u1_full_11school_2026-07-16`; the multidisc
machine's table `u1_edges_full_2026-07-05` holds only part of their works (A5046163960: 35 vs
131 authorship rows; A5080057811: 21 vs 227; A5075194454: 3 vs 55). The 62 July stars with
`percentile = NULL` in the July star set are human-verified admissions, not machine ranks.
Consequences:
* the run-2 economics event tables are void and were moved to `data/cal2026-10/_invalid_run2/`
  (kept for the record; chemistry and mathematics verdicts from that run are valid, and the
  one mathematics drop it reports, A5083769806 at 0.7941, is kept by author ruling 2026-08-13 —
  unchanged);
* economics is re-ranked on the 11-school extraction by `restake_econ11.py`, whose control is
  the 35 July event stars that carry a machine percentile;
* only the 17 rechecked stars can change status (their cleaned stocks); every other economics
  event keeps its July/August verdict, exactly as the 2026-08-28 caliber kept the old-79 rows.

Data disk: the physical data disk was attached; a byte-identical local mirror of
the S3 copies (plus the July-only artifacts copied from the SSD) is mounted at the canonical
path — see `<ssd_root>/MIRROR_NOTE/README.md` (`ssd_root` in config/paths.yaml).
