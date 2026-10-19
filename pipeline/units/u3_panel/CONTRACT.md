# U3 Panel - contract as code (5 producer→consumer boundaries)

> Each boundary = schema field names/types/required + semantics/constraints + owner. CI checks before dataset release that the output schema == the contract.
> No change to identification choices: U3 does not decide arrival / stars and does not redo disambiguation.

## Inbound boundaries (upstream → U3)

| Contract | producer → consumer | Key invariants | owner |
|---|---|---|---|
| C-U1→U3-affil | U1 → U3 | `WORKS_AFFIL` exactly 4 columns `{work_id, author_id, institution_id, raw_affiliation_strings:list<str>}`; `institution_id` may be None | U1 |
| C-U1→U3-year | U1 → U3 | `AUTHORSHIP_EDGES` exactly 3 columns `{work_id, author_id, publication_year:int16}`; `works_affil.PK ⊆ authorship_edges.PK` (guarded fail-loud by U3 step 2-b; if violated, report back to U1) | U1 |
| C-U1→U3-firstpub | U1 → U3 | `WORK_FIRST_PUB` exactly 3 columns `{author_id, first_pub_year:int16, first_pub_year_is_full_history:bool}`; `first_pub_year` = full-history min (#9), not collected-bounded | U1 |
| C-U2→U3-person | U2 → U3 | `PERSON_MAP` contains `{author_id, person_id}`; **U3 reads only these two columns**; author_id is canonical via the U0 author cmap (U3-E guard) | U2 |

## Outbound boundaries (U3 → downstream)

| Contract | producer → consumer | Key invariants | owner |
|---|---|---|---|
| C-U3→U4/U6 | U3 → U4/U6 | `PANEL` exactly 8 columns; PK `(person_id, year)` unique; **unbalanced (no row for a missing year, never padded with 0)**; `in_au_econ_dept_modal_hint` semantics = corroborating evidence for reconciliation, **not membership authority** (membership authority is U0.5 table B `DEPT_ROSTER_PANEL`) | U3 |

## 4 boundary disciplines (identification-neutral)

1. **Never pad a missing year with 0, never drop a person** - unbalanced panel; a missing year = truly "not there that year".
2. **Modal-institution folding does not decide arrival** - it computes only `primary_affil_id`; it never reads `affiliations[].years` (the Yves Zenou golden-test trap).
3. **`first_pub_year` is passed through, not frozen** - U3 supplies the true career first-publication year; freezing the cohort grouping key (#7) + the same/cross-generation flag (#15) happen in U6.
4. **`in_au_econ_dept_modal_hint` is non-authoritative** - the `_modal_hint` suffix means downstream must not use it as a membership criterion; membership authority = U0.5 table B.

## Known simplifications and boundaries

- **Deletion detection belongs to U1** - U3 does not decide whether an author left (that is an outcome, built downstream).
- **`is_modal` ≠ U4 arrival** - this column is a pure per-year modal marker and cannot be used alone as arrival evidence; U4 arrival must also require the old main affiliation's exit + truth_dates.
- **Single producer of modal** (identification-neutral, handed to the U4 owner): U3 alone produces the spine modal; `affil_timeline` serves as U4's reconciliation copy.
