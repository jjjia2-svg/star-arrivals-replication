# U2 (u2_resolve) CONTRACT - machine-readable contracts for 4 boundaries

> Charter: one contract per producer -> consumer boundary (schema + semantics + owner + SLA). Compatibility rule: once in the library, only optional fields may be added; changing a meaning or deleting a column is a breaking change. This first version was written together with the code and is updated with it.

## Boundary ① U1 -> U2 (input, U2 consumes)
- producer: U1 (u1_fetch) · consumer: U2 `m2_resolve.resolve.load_u1`
- reads the frozen derived tables in `<DATA_ROOT>/derived/u1_edges/`:
  - `works{work_id, publication_year, subfield_id, cited_by_count, work_type, ...}`
  - `authorship_edges{work_id, author_id, publication_year}` (the only source of coauthors)
  - `works_affil{work_id, author_id, institution_id, raw_affiliation_strings: list<str>}`
  - `work_text{work_id, title, abstract_text}`
  - `authors{author_id, display_name, orcid}`
  - `canonical_id_map{raw_id, canonical_id, id_type, is_deleted}`
- SLA: every author_id is in the U1 canonical space (normalisation is idempotent). U2's entry point `_assert_author_id_canonical_space` checks this; a leftover redirect -> `exit(EXIT_INPUT_NOT_CANONICAL=24)`.
- If missing: any of the three tables absent -> `_assert_upstream_fields` HALTs, pointing at "U1 full-scale three tables not shipped" (an engineering gap, not an open convention).
- Current state (stated plainly): the real-disk authors / work_text / canonical_id_map are not yet written in full -> prerequisite for the real-data smoke test (does not block fixture TDD).

## Boundary ② U0 -> U2 (foundation, U2 consumes)
- producer: U0 (u0_foundation) · consumer: U2 resolve.py + gate.py
- uses `common.{entity_resolve, reverse_validate, inst_lineage, manifest, atomic_io, ledger, schema, _redlines}` + `identity.{exit_codes, golden, constants}`
- SLA: U2 only orchestrates calls and never rewrites U0 algorithms. Every similarity threshold / weight is a null placeholder in U0 `_redlines.RED` -> `RedlineUnsigned` (a value must be set by hand). Exit codes are imported by name, never hard-asserted as integers.

## Boundary ③ U2 -> U3 (output, U2 produces)
- producer: U2 `resolve.py` · consumer: U3 panel
- `person_map{author_id, person_id, merge_reason, cluster_homogeneity, completeness, purity_flag, had_orcid}` (+ the gate writes back the cluster_purity columns)
- SLA: final only after the exit gate passes (canonical-sort by author_id); `person_id = "P_" + smallest author_id in the cluster`, order-independent and stable under member additions/removals. U3 reads only the two columns `{author_id, person_id}`.
- Forward declaration: U2 does not produce `is_star_coauthored` (that belongs to U4); it writes nothing to `PAPER_CONTRIB`.

## Boundary ④ (source) -> U2 candidate stars
- consumer: U2 `gate.py`'s "star + direct coauthors, 100% manual review" queue
- U2 takes the **entry parameter** `candidate_star_author_ids: set` (a superset of candidate stars). Owner / source = U0.5 table B department roster / U4 pre-run / test fixture.
- SLA (dependency direction fixed): the real `star_set` is produced by U4, after U2 -> U2 never depends on U4 output; with no candidates the 100%-queue runs empty without error; once U4 produces the real star_set, a superset check runs (candidates ⊇ true stars; a violation gives a WARN for U4 to review).
- Note: U1 has no `frontier_authors` table (the spec was mistaken; all 10 writers were checked); candidate stars must never be read from a table that does not exist.

## Known simplifications and limits (recorded plainly, after the adversarial review)

- **B1 fixed**: `run_resolve` now reads `works_affil` and attaches `raw_affiliation_strings` to each record, so `affil_conflict` in `cluster_block` actually takes effect (same name, different institution: not merged). Guarded by the red test `test_same_name_different_affil_not_merged`.
- **M1 - deletion detection belongs to U1**: `_assert_author_id_canonical_space` only checks whether an author_id is a redirect source (raw≠canonical); it does **not** check is_deleted (entities deleted in OpenAlex). Filtering deleted entities is the job of U1's fetch layer; the U2 entry point only guards the canonical space. To make U2 also reject deleted authors, use `replay_merged_ids(..., deletion_sentinels=DELETION_SENTINELS_AUTHORS)`.
- **L3 - person_map.completeness is a placeholder**: cluster_purity.topic_completeness, and the value written back into person_map.completeness, is currently always 1.0 (a single cluster cannot be tested for splitting without supervision). **The real completeness is computed with ground truth in exit gate G1 (bcubed_recall)**. Downstream must not treat person_map.completeness as real completeness; see the gate evidence for the real value.
- **L2 - multi_inst uses the raw institution_id**: the institution diversity in the over-merge probe currently counts distinct institution_id (not the parent-institution folding of `fold_to_canonical`). Because multi_inst **never triggers over-merge on its own** (weak-signal redline), the only effect is more diagnostic-column hits. It will be upgraded to parent-institution folding once the INSTITUTIONS registry is loaded; **never promote multi_inst to a hard signal**.
- **Real-data orchestration still to integrate**: `run_m2_exit_gate` is currently the in-memory version; the real-data version (read person_map.parquet + build a golden frame from the Zenou vertical slice + compute the actual works_count) is a real-data integration, waiting for the full U1 three tables (authors/work_text/canonical_id_map) to ship. Fixture-level TDD is currently all green (55 tests).
