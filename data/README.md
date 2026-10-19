# data/

Every folder here belongs to one version of the data. The paths file in force selects the version
that `analysis/run_all.sh` reads.

| version | events | folders | selected by |
|---|---|---|---|
| **the report as submitted** | 377 | `data/report/` (index: `data/report/README.md`) | `config/paths.yaml` (the default) |
| October 2026 | 184 | `data/frames/`, `data/cal2026-10/`, and the recorded estimates in `analysis/expected/` | `SAR_PATHS_CONFIG=$PWD/config/paths_october.yaml` |
| August 2026 | 187 | `data/cal2026-08-28/` (frames, estimates, cloud records) | read by the tests only |

Shared by all versions:

- `fwci/`: the field-weighted citation benchmarks and the snapshot scan manifests.
- `raw_verified/`: the verified rosters and arrival-event tables (OpenAlex ids, years and codes),
  and the economics edge supplement.
- `paper_inputs/`: inputs of the report's figures and text (star origins, the map's land files, the
  quoted ABS figures and other frozen inputs).
- `stage_payloads/`: frozen star-event verdicts that a pipeline stage reads (ids, verdicts and
  arrival years).

Earlier runs, one folder each (estimates, run logs and manifests):

- `estimates/`: archived cloud results of the August 2026 chain that are not re-run here.
- `predate_2026-08-28/`, `predate_p1_2026-08-30/`: the arrival-date shift tests, August version.
- `robustness_2026-08-29/`, `robustness_2026-08-29_b/`, `robustness_2026-08-31/`: robustness batteries
  on the August version (bounds, levels, departures, double stars, no-centre rosters, permutations,
  leave-one-out).
- `robustness_afar_cuts_2026-08-30/`: the Panel 3 topic-cut grid.
- `robustness_2026-09-10_p3pos/`: Panel 3 event-level checks on the dose-above-zero cut.
- `robustness_2026-09-12_dscomp/`: the date-shift comparison.
- `robustness_2026-09-13_inpost_diag/`, `robustness_2026-09-13_verified_pool/`: the in-post
  diagnostic and the verified-roster pool.
- `inference_afar_pos_2026-08-30/`, `null_sim_pos_2026-08-30/`: permutation inference and the
  no-effect simulation for Panel 3, with their cloud records in `cloud_custody_null_perm_2026-08-30/`.
- `sensitivity_2026-08-30/`: Panel 1 parallel-trends sensitivity bounds.
- `arrival_verification_2026-09-12/`: one arrival-year check (ids and codes).

The robustness results of the October version are under `data/cal2026-10/robustness/`, and those of
the report under `data/report/cal/robustness/`. Every frozen file is pinned by sha256, in
`data/MANIFEST.sha256` or in its folder's own `MANIFEST.sha256`; `tools/verify_manifest.py` checks
them.
