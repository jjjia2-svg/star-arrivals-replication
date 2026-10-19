# Data for the submitted report

The default data version: 377 arrivals (economics 173, chemistry 97, mathematics and statistics 107),
1999-2024. `config/paths.yaml` selects this directory. The October and August versions remain separate;
see `data/README.md`.

| Folder or file | Contents |
|---|---|
| `CANON.json` | Data-version identifier, the six folder keys and analysis switches |
| `MANIFEST.sha256` | Original final-run manifest; its bytes are retained when this canon is installed |
| `frames/` | Analysis panels; the economic event ledger is documentation, not an estimator input |
| `expected/` | The 27 recorded headline estimates |
| `cal/` | Events and counts, rosters, panel-build reports, ranking and computed robustness results |
| `cal_intermediates/` | Economics pair table, shipped as `pairs_unified.csv.xz` |
| `raw_verified/` | Verified rosters and the carried economics edge supplement; the chemistry/mathematics verification table is the independent October table |
| `paper_inputs/` | Star-origin inputs, basemap files and other frozen figure inputs |
| `PACKED.tsv` | Unpacked path, sha256 and bytes, plus the compressed sha256 and bytes |
| `custody/` | Original input hashes and fetched estimates for the four large cells; `RESOURCES.md` and `resources.json` record all 27 cells' measured resources; a separate manifest covers them |
| `paper_numbers/` | Ten numbered ledgers, dated `2026-10-24`, with a separate manifest |

October basenames are retained so the same readers work with both versions. In particular,
`cal/_invalid_run2/restake_2026-10.csv` is this report's ranking table; its historical directory name
does not identify an invalid report run.

Stage 1 restores the pair CSV atomically after checking both sizes and hashes in `PACKED.tsv`.
The 481,997,636-byte CSV is ignored by git; its 4,804,448-byte compressed copy is shipped. The final-run
canon contains 844 files totalling 303,181,052 bytes before this index, the paper ledgers and custody
are added. No packed member exceeds 21,145,600 bytes.

The paper ledgers keep their original numeric values and keys, boolean flags and nulls. Private
provenance fields and text values are omitted; list positions are retained. The date is the final
run's ledger label, not the release date. These reference numbers do not make the manuscript-dependent
figure and table generators self-contained.

In the public copy, personal columns (`name`, `display_name`, evidence links and notes, `human_evidence`,
`source_docs`, `recheck`) are removed where present. Estimation panels, recorded estimates, packed
pairs and custody remain byte-identical. The economics event ledger's notes use these code tables:

| Column | Codes and meaning |
|---|---|
| `verify_source` | `human_batch_2026-08-09`, `human_prior_not_rechecked`, `human_batch_2026-08-10`: recorded verification batches; `llm_two_round_2026-09-13`: two AI checking rounds; `collected_2026-10`: archived staff lists and handbooks with checked OpenAlex ids |
| `human_verified` | Recorded verification flag: 879 of 2,640 economics roster rows are true; it is not a blanket claim about the roster |
| `year_source` | `list`: staff-list years; `list_single`: a single listed year; `list+personal`: staff lists supplemented by a personal public source |
| `reason` | Empty; `poach-gate false negative (OpenAlex affiliation backfill)`; `STAGE_A_zero_coupling`; `STAGE_B_one_per_person`; `STAGE_A_dose_tier`; `added_2026-10` for an accepted addition |
| `evidence_source` | Fixed descriptions of the recorded frame/coverage checks, or `signed_add_list_r1 (not shipped)`; personal links are removed |

Each folder has a sha256 manifest. The root manifest is kept as supplied; the extra `custody/` and
`paper_numbers/` manifests cover the release additions. Public-export manifests reflect the scrubbed
files, with changes recorded in `HASH_CROSSWALK.md`.
