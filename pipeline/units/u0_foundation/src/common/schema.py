"""U0 common/schema.py — the single source of truth for every table's column contract (all tables) + assert_matches_schema.

A caliber-neutral cross-cutting base: the schema constants of 28 tables, each a dict[str, str] (column name -> type string).
Column names and types are used verbatim; do not invent any.

Enforced check: assert_matches_schema(row_keys, schema, *, label) — the row key set must equal the schema key set
exactly; one extra or one missing key raises. Downstream tables use it to keep the schema consistent before writing to disk.

Schema constant count = 28 (3 base + 9 U1 + 2 U0.5 + 2 U2 + 3 analysis layer + 9 downstream).
"""
from __future__ import annotations

# ===========================================================================
# B.1 Base/ledger tables — 3 tables
# ===========================================================================

# [1] CANONICAL_ID_MAP — raw->canonical id map; exactly 4 keys (a missing is_deleted raises)
#     One table holds several kinds of rows, told apart by id_type taken from ENTITY_TO_IDTYPE values. Written under u1_edges/.
CANONICAL_ID_MAP: dict[str, str] = {
    "raw_id": "str",
    "canonical_id": "str",
    "id_type": "category",
    "is_deleted": "bool",
}

# [2] LEDGER_EVENT — row contract of the append-only event log; status in ok/transient/permanent/skip
LEDGER_EVENT: dict[str, str] = {
    "op_id": "str",
    "status": "category",
    "shard_id": "str",
    "idempotency_key": "str",
    "ts": "str",
    "reason": "str",
}

# [3] TALLY — row contract of the six-key reconciliation tally; op_id_arm in ok/"N/A" (M1 marks N/A)
TALLY: dict[str, str] = {
    "stage": "str",
    "expected": "int64",
    "kept": "int64",
    "failed": "int64",
    "skipped": "int64",
    "balanced": "bool",
    "op_id_arm": "category",
}


# ===========================================================================
# B.2 U1 output tables (written by M1) — 9 tables
# ===========================================================================

# [4] AUTHORSHIP_EDGES — PK (work_id, author_id); fixed at exactly 3 columns; never put raw_affil in it
AUTHORSHIP_EDGES: dict[str, str] = {
    "work_id": "str",
    "author_id": "str",
    "publication_year": "int16",
}

# [5] REFS_EDGES — PK (work_id, referenced_work_id); the column name follows the official anchor referenced_work_id
REFS_EDGES: dict[str, str] = {
    "work_id": "str",
    "referenced_work_id": "str",
}

# [6] WORKS — PK work_id; subfield_id must be kept; fwci/is_in_top_* are None when the snapshot lacks them
WORKS: dict[str, str] = {
    "work_id": "str",
    "publication_year": "int16",
    "work_type": "category",
    "subfield_id": "category",
    "fwci": "float32",
    "cited_by_count": "int64",
    "referenced_works_count": "int64",
    "has_references": "bool",
    "is_paratext": "bool",
    "is_retracted": "bool",
    "is_in_top_1_percent": "bool",
    "is_in_top_10_percent": "bool",
}

# [7] AUTHORS — PK author_id; fixed at 3 columns
#     Placeholder: if the m0 snapshot is found to contain display_name_alternatives, widen to 5 columns after manual review; the default is 3 columns.
AUTHORS: dict[str, str] = {
    "author_id": "str",
    "display_name": "str",
    "orcid": "str",
}

# [8] WORK_TEXT — PK work_id; fixed at 3 columns including title; abstract is reconstructed from inverted_index
WORK_TEXT: dict[str, str] = {
    "work_id": "str",
    "title": "str",
    "abstract_text": "str",
}

# [9] WORKS_AFFIL — PK (work_id, author_id); the key to resolving the 13 fragments in disambiguation; kept as a separate table (do not collide with AUTHORSHIP_EDGES)
WORKS_AFFIL: dict[str, str] = {
    "work_id": "str",
    "author_id": "str",
    "institution_id": "str",
    "raw_affiliation_strings": "list<str>",
}

# [10] WORK_FIRST_PUB — PK author_id; true career first-publication year; feeds PANEL.first_pub_year
WORK_FIRST_PUB: dict[str, str] = {
    "author_id": "str",
    "first_pub_year": "int16",
    "first_pub_year_is_full_history": "bool",
}

# [11] INSTITUTIONS — PK institution_id; promoted to a first-class product; source of the fold_to_canonical output
#      Coverage contract = all distinct institution_id values that appear in works_affil/authorship (including all foreign ones)
#      U1 alignment: add the two columns display_name + country_code = 7 columns.
#        - country_code is the key to deciding whether an institution is foreign (e.g. SE=Stockholm -> is_foreign); fold_to_canonical does not read it, it only serves downstream foreign-institution tests and human readability.
#        - associated_institutions stays list<dict> (fold_to_canonical path3 reads assoc.relationship/type/id; list<str> would not work -> never change it to list<str>).
#        - The column named type is unchanged (inst_lineage path3 reads the type field of each per-assoc dict, not a column of this table; keep the change minimal).
INSTITUTIONS: dict[str, str] = {
    "institution_id": "str",
    "display_name": "str",
    "country_code": "str",
    "type": "category",
    "lineage": "list<str>",
    "associated_institutions": "list<dict>",
    "ror": "str",
}

# [12] FWCI_BASELINE_POP — PK (subfield_id, year, work_type); the denominator population of the self-built field-normalized citation ratio
#      32-bucket log histogram, bounded at about 23MB; cit_hist_32 = diagnostic/robustness carrier
FWCI_BASELINE_POP: dict[str, str] = {
    "subfield_id": "category",
    "year": "int16",
    "work_type": "category",
    "work_count": "int64",
    "citation_sum": "int64",
    "cit_hist_32": "list<int32>",
}


# ===========================================================================
# B.3 U0.5 department roster tables — 2 tables
# ===========================================================================

# [13] ECON_DEPT_REGISTRY (table A); subfield_primary fixed to ["2002"]
#      openalex_inst_id = the university-level alignment bridge from table B to events.dept_id
ECON_DEPT_REGISTRY: dict[str, str] = {
    "dept_key": "str",
    "university": "str",
    "openalex_inst_id": "str",
    "dept_name_variants": "list<str>",
    "is_business_school": "bool",
    "subfield_primary": "list<str>",
    "subfield_robustness_flagged": "list<str>",
    "subfield_excluded": "list<str>",
    "source": "category",
    "human_verified": "bool",
}

# [14] DEPT_ROSTER_PANEL (table B); interval form, keyed by raw author_id
#      evidence in official_roster/wayback_snapshot/raw_affil_year/arc_grant/orcid_employment/manual
DEPT_ROSTER_PANEL: dict[str, str] = {
    "dept_key": "str",
    "author_id": "str",
    "display_name": "str",
    "year_start": "int16",
    "year_end": "int16",
    "evidence": "category",
    "confidence": "category",
    "human_verified": "bool",
}


# [14v2] DEPT_ROSTER_PANEL_V2 (table B v2) — roster/schema-layer fix for two root causes.
#   Cause D: when centre members were added, affil_type was deliberately written only into the evidence string,
#     so downstream could not filter on it by machine ("filter centre members by field / switch to a
#     dept-only robustness tier at any time" was not executable) -> promoted to a proper column.
#   Cause E: 83% of arrival years were not human-checked and their source was untraceable -> added a
#     year_start_provenance column holding a source sub-label.
#   Value domains (mechanical layer, not an identification decision):
#     affil_type in dept_only (entered only from a department roster) / centre_only (entered only from a centre roster) / both
#     year_start_provenance in bio_stated (year stated explicitly on a page/CV/ORCID) /
#       snapshot_first_seen (first seen in the snapshot, left-censored) / unknown (the source cannot be
#       inferred from the evidence string, including the Pure active-publication interval of
#       official_roster; this has no basis and is not passed off as an explicit statement)
#   Rule: the old 8-column DEPT_ROSTER_PANEL is left **untouched, not one character** (the frozen
#   registry_v3 and the u2/u4/u6 consumers still assert 8 columns); V2 is used only for new roster products in
#   new dated directories; for the backfill function see u0p5_dept_roster/src/roster/panel_v2.py.
DEPT_ROSTER_PANEL_V2: dict[str, str] = {
    **DEPT_ROSTER_PANEL,
    "affil_type": "category",
    "year_start_provenance": "category",
}


# [14b] Three intermediate tables of the historical-roster byline track
#   BYLINE_YEAR_EVIDENCE.source_work_ids = the key to tracing each year back to its source (red test: a year point with no source work always raises)
#   match_style (found in a real-data smoke test): archive sources (RePEc style) stamp an author's "current
#   unit" onto their historical papers
#   ('Monash University - Department of Economics' pulled the candidate year of Yves Zenou back to 1998, true arrival 2016) ->
#   printed (department first / nested hierarchy = printed on the paper) vs stamped (university first + a bare separator joining directly = archive stamp);
#   a year point with n_printed_style=0 is supported by stamping only. Only a mechanical label is attached; how to use it is governed by a threshold that is still unset.
BYLINE_DEPT_HITS: dict[str, str] = {
    "work_id": "str",
    "author_id": "str",
    "dept_key": "str",
    "matched_phrase": "str",
    "institution_id": "str",
    "match_style": "category",
}

BYLINE_YEAR_EVIDENCE: dict[str, str] = {
    "author_id": "str",
    "dept_key": "str",
    "year": "int16",
    "n_papers_that_year": "int32",
    "n_printed_style": "int32",
    "source_work_ids": "list<str>",
}

# Skeleton = a subset of table B (same 8 columns; evidence is fixed to raw_affil_year, guaranteed by the writer, assert_matches_schema before writing the table)
BYLINE_ROSTER_SKELETON: dict[str, str] = dict(DEPT_ROSTER_PANEL)


# ===========================================================================
# B.4 U2 entity-resolution tables — 2 tables
# ===========================================================================

# [15] PERSON_MAP; merge_reason ∈ block_cluster/orcid_prior/raw_affil_text/golden_manual
#      purity_flag ∈ clean/suspected_overmerge/low_confidence
PERSON_MAP: dict[str, str] = {
    "author_id": "str",
    "person_id": "str",
    "merge_reason": "category",
    "cluster_homogeneity": "float32",
    "completeness": "float32",
    "purity_flag": "category",
    "had_orcid": "bool",
}

# [16] CLUSTER_PURITY — cluster purity diagnostics
# Over-merge fix A (13 -> 14 columns): new column distinct_orcid_hit = the raw signal that a cluster holds >=2
#   distinct valid ORCIDs (a corroborated flag for wrong merges across different ORCIDs). The flag rule =
#   distinct_orcid_hit AND (field conflict OR institution conflict), assembled in
#   gate.compute_cluster_purity and folded into overmerge_suspect;
#   it only detects and sends cases to the human-review queue, and never splits automatically.
# Root-cause fix (14 -> 15 columns): new column quality_representative_author_id = a per-cluster
#   quality-representative id diagnostic (among members that are field-consistent AND name-compatible,
#   the one with the highest cited_by_count; with no qualifying member -> None). A pure diagnostic column: it does not
#   touch person_id / min-id grouping / the 0.8 threshold / the clustering logic (same rule as flagA,
#   "detect only, never split automatically").
CLUSTER_PURITY: dict[str, str] = {
    "person_id": "str",
    "n_works": "int32",
    "topic_homogeneity": "float32",
    "topic_completeness": "float32",
    "n_name_variants": "int32",
    "name_incompat_hit": "bool",
    "dirty_orcid_hit": "bool",
    "affil_conflict_hit": "bool",
    "topic_outlier_hit": "bool",
    "distinct_orcid_hit": "bool",
    "overmerge_suspect": "bool",
    "ejected_work_ids": "list<str>",
    "purity_flag": "category",
    "topic_source": "category",
    "quality_representative_author_id": "str",
}


# ===========================================================================
# B.5 Analysis-layer tables — 3 tables
# ===========================================================================

# [17] ANALYSIS_FRAME — 15 columns; PK (incumbent_person_id, year, star_person_id, event_id)
#      The group column is deleted (13 -> 12); same-generation flag / event_time are derived in the regression layer and not stored as columns
#      Caliber update (12 -> 15):
#        - pub_frac renamed to pub_count (meaning = a pure count, each paper counts 1; the old name frac was misleading)
#        - new pub_count_ex_star (pure count without star papers) + fwci_mean / fwci_mean_ex_star
#          (mean quality per paper; a year with 0 papers = NA, never filled with 0); the other 11 columns are unchanged
#      fwci_frac/pub_count/fwci_frac_ex_star/pub_count_ex_star/fwci_mean(_ex_star) come from OUTPUT;
#      the count/mean columns use a float32 carrier: in the U6 assembly layer, years after a fully exited person's exit are
#      recorded as NA, and an int carrier cannot store NA (this takes effect in U6; this layer only registers the schema)
ANALYSIS_FRAME: dict[str, str] = {
    "incumbent_person_id": "str",
    "year": "int16",
    "star_person_id": "str",
    "event_id": "str",
    "treated": "bool",
    "post": "bool",
    "dose_coupling": "float32",
    "dose_low_confidence": "bool",
    "age_gap": "float32",
    "fwci_frac": "float32",
    "pub_count": "float32",
    "fwci_frac_ex_star": "float32",
    "pub_count_ex_star": "float32",
    "fwci_mean": "float32",
    "fwci_mean_ex_star": "float32",
}

# [18] PAPER_CONTRIB — 8 columns; fractional count (denominator = number of bylines N)
#      The is_star_coauthored column sits in the main table, but the FWCI baseline node never reads it (CI red test)
PAPER_CONTRIB: dict[str, str] = {
    "work_id": "str",
    "incumbent_person_id": "str",
    "person_id": "str",
    "publication_year": "int16",
    "frac_credit": "float32",
    "fwci": "float32",
    "is_star_coauthored": "bool",
    "subfield_id": "category",
}

# [19] OUTPUT — 12 keys (2 primary keys + 10 value keys); per-person-per-year (with year)
#      citation_weighted deleted: it was a clone of fwci_frac (redundant, wrong value) with zero consumers.
#      Caliber update (6 -> 12; the exact caliber of each key is in the identity/output_rule.aggregate_output docstring):
#        pub_count          renamed from n_works; a pure count, each paper counts 1, including papers with missing fwci
#        pub_count_ex_star  pure count of papers with no star in the byline (exclusion set = is_star_coauthored,
#                           exactly the same source as fwci_frac_ex_star) — addresses the quantity vs quality question
#        n_works_frac       sum of frac_credit, a fractional count (robustness column, not in the U6 frame)
#        fwci_frac          sum of frac_credit x fwci, only where fwci is non-NA (unchanged, headline outcome)
#        fwci_frac_ex_star  same, over non-star co-authored papers only (unchanged)
#        fwci_full          sum of fwci, full count with no splitting, only where fwci is non-NA (robustness column for matching the literature, not in the frame)
#        fwci_full_ex_star  same, over non-star co-authored papers only
#        fwci_mean          sum of fwci / number of non-NA fwci rows; denominator 0 -> NA (a year with 0 papers = NA, never filled with 0)
#        fwci_mean_ex_star  same, over non-star co-authored papers only; 0 rows after exclusion -> NA
#        quality            stays a None placeholder (self-built field normalization, computed across tables in U5, untouched in this layer)
OUTPUT: dict[str, str] = {
    "incumbent_person_id": "str",
    "year": "int16",
    "pub_count": "int32",
    "pub_count_ex_star": "int32",
    "n_works_frac": "float32",
    "fwci_frac": "float32",
    "fwci_frac_ex_star": "float32",
    "fwci_full": "float32",
    "fwci_full_ex_star": "float32",
    "fwci_mean": "float32",
    "fwci_mean_ex_star": "float32",
    "quality": "float32",
}


# ===========================================================================
# B.6 Downstream-unit schema constants (carrier structure only, no identification-caliber values) — 9 tables
# ===========================================================================

# [20] PANEL — 8 columns; PK (person_id, year); the researcher x year backbone (unbalanced, a missing year = truly absent)
#      primary_affil_id: bare id of the modal canonical edu institution of that year; none -> sentinel PANEL_AFFIL_NONE
PANEL: dict[str, str] = {
    "person_id": "str",
    "year": "int16",
    "primary_affil_id": "str",
    "raw_affil": "str",
    "in_au_econ_dept_modal_hint": "bool",
    "n_works_year": "int32",
    "first_pub_year": "int16",
    "first_pub_year_is_full_history": "bool",
}

# [21] AFFIL_TIMELINE — 9 columns; PK (person_id, year, work_id, raw_inst_id, raw_affil_slot)
#      per-work institution detail; is_modal: a pure per-year mode flag, not an arrival criterion
AFFIL_TIMELINE: dict[str, str] = {
    "person_id": "str",
    "year": "int16",
    "work_id": "str",
    "raw_inst_id": "str",
    "raw_affil_slot": "int32",
    "canonical_affil_id": "str",
    "n_works_at_affil": "int32",
    "is_modal": "bool",
    "raw_affil": "str",
}

# [22] STAR_SET — 14 columns; PK author_id; one row per frozen candidate, carrying the star flags (stars are picked by filtering on is_star_1pct/5pct)
#      Aligned with the frozen state (14 columns keyed by author_id;
#      measured on the on-disk u4 star_set.parquet, produced by u4 run_u4.py);
#      the old 9-column layout (star_person_id/metric/evidence_source/dist_to_cutoff/...) is no longer used.
#      Key = OpenAlex author_id (the ranking reference pool = all author_id; the person key is mapped via the U2 person_map);
#      ranking caliber = cumulative raw citation stock up to the year before arrival (stock; no metric label column is stored, the caliber is recorded as provenance);
#      the two bool star flags is_star_1pct/is_star_5pct already include the seniority threshold (age_eligible, min_academic_age=2) and the cell gate;
#      cell_n / is_star_1pct / is_star_5pct are nullable — None for people not in the pool (thin cells);
#      percentile = float64 (parquet double); a pure foreign poach must additionally be combined with is_foreign_poach.
STAR_SET: dict[str, str] = {
    "author_id": "str",
    "name": "str",
    "dept": "str",
    "arrival": "int64",
    "subfield": "str",
    "age_bin": "str",
    "academic_age": "int64",
    "stock": "int64",
    "percentile": "float64",
    "cell_n": "int64",
    "is_star_1pct": "bool",
    "is_star_5pct": "bool",
    "age_eligible": "bool",
    "is_foreign_poach": "bool",
}

# [23] EVENTS — 11 columns; PK event_id; canonical-sort by (star_person_id, arrival_year); a single file with no p-level dimension
#      dept_id = canonical education parent (university level); t_minus_1 = derived from arrival_year by run_m7a
#      arrival_source has six values; arrival_evidence_strength in strong/modal_shift
EVENTS: dict[str, str] = {
    "event_id": "str",
    "dept_id": "str",
    "star_person_id": "str",
    "arrival_year": "int16",
    "t_minus_1": "int16",
    "arrival_source": "category",
    "arrival_evidence_strength": "category",
    "modal_inst_year": "bool",
    "prior_main_exited": "bool",
    "min_tenure_ok": "bool",
    "departed_year": "int16",
}

# [24] FWCI_BASELINE — derived table (not FWCI_BASELINE_POP); PK (subfield_id, year, work_type)
#      expected caliber = arithmetic mean; coexists with the accumulator population without conflict
FWCI_BASELINE: dict[str, str] = {
    "subfield_id": "category",
    "year": "int16",
    "work_type": "category",
    "expected_citations": "float64",
}

# [25] GENERATION_PERSON — PK (person_id), does not include year
#      gen_pk_includes_year=False: the generation grouping key is frozen once at the arrival year and does not vary with the panel year -> the PK of this table has no year
GENERATION_PERSON: dict[str, str] = {
    "person_id": "str",
    "academic_age": "int16",
    "cohort_age_bin": "str",
    "bin_n_authors": "int32",
    "bin_below_min": "bool",
}

# [26] GENERATION_PAIR — PK (incumbent_person_id, star_person_id, event_id), three elements, no year
#      continuous academic-age gap; the same-generation flag is derived in the regression layer and not stored in this table; no group/treated (those are in GROUPS_ABC)
GENERATION_PAIR: dict[str, str] = {
    "incumbent_person_id": "str",
    "star_person_id": "str",
    "event_id": "str",
    "age_gap": "float32",
}

# [27] PAIRWISE_DOSE — 11 columns; PK (incumbent_person_id, star_person_id, event_id, degree)
#      canonical-sort by the full PK; coupling_share = the main dose (shared-reference coupling up to t-1)
#      topic_cos/embed_cos = secondary doses (never enter dose_coupling); degree 1 = direct co-authorship / 2 = via an intermediary
#      Completed to the 11 columns of the dose spec: added degree2_bridge_frozen
#      (the double-bridge-edge freeze flag: whether both bridge edges of a degree-2 row exist before t-1;
#       False -> coupling_share is already recorded as 0 and the row serves only post-arrival robustness), column order as in the spec.
PAIRWISE_DOSE: dict[str, str] = {
    "incumbent_person_id": "str",
    "star_person_id": "str",
    "event_id": "str",
    "coupling_share": "float32",
    "topic_cos": "float32",
    "embed_cos": "float32",
    "coupling_coverage": "float32",
    "frozen_at_year": "int16",
    "degree": "int8",
    "degree2_bridge_frozen": "bool",
    "boundary_sensitive": "bool",
}

# [28] GROUPS_ABC — incumbent membership table (no A/B/C group column, no same_cohort_field_near)
#      treated rows PK (incumbent, star, event); C rows PK (incumbent, control_star, matched_treated_event)
#      control_star_person_id / matched_treated_event_id = specific to C rows (NA on treated rows); foreign keys are never minted silently
GROUPS_ABC: dict[str, str] = {
    "incumbent_person_id": "str",
    "star_person_id": "str",
    "event_id": "str",
    "treated": "bool",
    "control_star_person_id": "str",
    "matched_treated_event_id": "str",
}


# ===========================================================================
# Enforced check function — assert_matches_schema (downstream tables keep the schema consistent before writing to disk)
# ===========================================================================

class SchemaMismatchError(ValueError):
    """The row key set differs from the schema key set (extra or missing both count)."""


def assert_matches_schema(row_keys, schema: dict[str, str], *, label: str) -> None:
    """Guard "the row key set equals the schema key set exactly": one extra or one missing key raises.

    Arguments:
        row_keys: the key set of one data row (iterable; set/dict.keys()/list all work).
        schema:   the schema constant dict[str, str] of that table (column name -> type).
        label:    table name, used to locate the error.

    Raises:
        SchemaMismatchError — when the row key set != the schema key set (reports the extra keys + the missing keys).
    """
    row_set = set(row_keys)
    schema_set = set(schema.keys())
    if row_set == schema_set:
        return
    extra = row_set - schema_set      # Keys the row has in excess
    missing = schema_set - row_set    # Keys the row is missing
    raise SchemaMismatchError(
        f"[{label}] row key set does not match the schema key set: "
        f"extra={sorted(extra)} missing={sorted(missing)}"
    )
