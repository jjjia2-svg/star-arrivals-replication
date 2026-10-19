# U2 - u2_resolve (entity resolution / disambiguation)

## ① What this unit does
Merges the several canonical author_ids that OpenAlex split one real person into back into a single `person_id`. The only product is `person_map` (author_id -> person_id mapping), used by U3 panel / U4 star_identify and every downstream join. The top risk is over-merge: wrongly merging a star's papers into a local namesake creates a false spillover and contaminates everything downstream.

## ② Inputs (upstream contract, see boundaries ①② in CONTRACT.md)
- U1 derived tables (`derived/u1_edges/`): works / authorship_edges / works_affil / work_text / authors / canonical_id_map
- U0 `common/` + `identity/` foundation (called only, never rewritten)
- ground-truth fixtures `golden/` (source=external, isolated: never fed back into the rules)

## ③ Outputs (downstream contract, see boundary ③ in CONTRACT.md)
person_map (main) + cluster_purity / cluster_quality / manual-review queue CSV / gate_provenance.json / calibration report / tally.json, all written to `<DATA_ROOT>/derived/u2_resolve/`.

## ④ How to run
`PYTHONPATH=units/u0_foundation/src:units/u1_fetch/src:units/u2_resolve/src`
- Produce person_map: `python -m m2_resolve.resolve --data-root <DATA_ROOT>` (the entry point first runs the canonical-space assertion)
- Exit gate: `python -m m2_resolve.gate --data-root <DATA_ROOT>` (U0 validate_resolution + Zenou golden standard + Monash attribution + freeze)

## ⑤ Tests / gates (how correctness is checked)
At least one TDD red test per file; entry guard on the canonical id space (redirect -> exit 24); three #11-a red tests (Zenou has no orcid_prior / GT-ORCID never enters the input / grep of production code finds zero hits); Zenou two-way golden-standard e2e (works in [550,620] + same-name others ejected + Monash, not Stockholm + enters the manual-review queue); determinism / idempotence (same sha on two runs); threshold-redline sentinel (the production entry raises RedlineUnsigned on null; grep finds nothing hard-coded).

## ⑥ Redlines / where the conventions come from (the identification layer is set by hand)
Identification conventions: see `contracts/redlines.yaml`. U2 involves: redline #11 (B³ by direction / ORCID hard-seed precondition / institution as a weak feature / over-merge is the top disaster) + #11-a (Zenou has had_orcid=False; ORCID is never used as a hard seed) + #11-b (under-merge is caught by completeness) + #11-c (recall floor for small departments: measure first, then set) + #11-d (two-way hard exit gate, direction fixed by measurement). All 5 numeric knobs are null -> raise, and must be set by hand; U2 only implements values that have been set and never invents a convention.

## ⑦ Known pitfalls / limits (stated plainly)
- U2's input author_id is U1's canonical normalisation, **not** a person_id (person-level merging is U2's own job).
- Zenou has no ORCID in OpenAlex (had_orcid=False): fragments are merged back using raw_affil + title + union-find + 100% manual review, never via an ORCID override; GT-ORCID is only a manual cross-check reference and never enters the pipeline input.
- Candidate stars = a superset passed in at the entry point (the real star_set is produced by U4, after U2); U1 has no frontier_authors table.
- Fitting thresholds to a synthetic Zenou fixture is circular: it proves the mechanism, not real calibration; thresholds are always set by hand.
- B³ / Pairwise are diagnostics only, not gates; the hard gates use U0 recall / precision / completeness / homogeneity.
- The full real-disk authors / work_text / canonical_id_map tables are not written yet -> prerequisite for the real-data smoke test (does not block fixture TDD).
