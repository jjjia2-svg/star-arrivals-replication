"""The single source of truth for pipeline-wide exit codes.

U0 is the issuer of the numbers and registers up to GOLDEN_FAIL=18.
Only the seven codes 12-18 are registered; the range 1-11 is unassigned (the SystemExit(1) in quota_guard
is a bare, unnumbered 1) -> it is not included in this table and no named constant is added for it.

Rule: downstream tests assert "exception type + distinguishability" and never hard-assert a specific code value;
the specific integers are an engineering convention (not an identification red line). This file provides named constants so that downstream code uses names instead of bare numbers.
"""

# --- Registered codes (12-18, never invent values) ---
RESOLVE_GATE_FAIL = 12    # The U2 disambiguation gate failed (registered by contract)
PROVENANCE_MISMATCH = 13  # Any element of the provenance four-tuple differs (provenance HALT)
STRUCTURAL_GATE_FAIL = 14  # Frame structure gate (12-column schema / row sources inconsistent)
TALLY_IMBALANCE = 15      # The six-key tally is unbalanced (reconciliation arm)
CAPACITY_GATE_FAIL = 16   # Disk gate (preflight)
CORRUPT_SHARD = 17        # snapshot_reader torn shard (never silently treated as empty)
GOLDEN_FAIL = 18          # Yves Zenou gold standard: structural_pass=False

# --- U1 alignment additions (19-23): used by the new U1 fetch/write gates, U0 is the only issuer ---
#   The specific integers are an engineering convention (not an identification red line); numbers continue from 19, do not collide with 12-18 and stay out of the 1-11 range.
#   Names carry the EXIT_ prefix = the names the U1 module imports directly (EXIT_FIELDS_MISSING etc.).
EXIT_FIELDS_MISSING = 19         # The snapshot field probe lacks a required key (a drift safety net, M1 assert_snapshot_fields_present)
EXIT_FRONTIER_MISS = 20          # pass_c extended-set rescan hits < frontier_count (the boundary rescan missed hits)
EXIT_DEDUP_NONZERO = 21          # compact_dedup != 0 (count(*)-count(DISTINCT pk) is non-zero, duplicate pk)
EXIT_CANONICAL_SPACE_SPLIT = 22  # Space guard: a foreign key is not within the same canonical space (works_affil.author_id not within authors etc.)
EXIT_MERKLE_INVALID = 23         # The entry-time Merkle root does not match (the frozen snapshot was changed / the reproducibility anchor is inconsistent)

# --- U2 alignment addition (24): used by the U2 entity-resolution entry guard, U0 is the only issuer ---
#   Numbering continues at 24 (13 is already PROVENANCE_MISMATCH, 12-23 are fully taken); an engineering convention, not an identification red line.
EXIT_INPUT_NOT_CANONICAL = 24    # U2 entry: author_id still has an unresolved redirect (_assert_author_id_canonical_space)

# --- Historical-roster byline track (25-29; numbers continue, do not collide with 12-24 and stay out of the 1-11 range) ---
EXIT_ROSTER_UPSTREAM_FAIL = 25   # U1 full run not produced / raw_affiliation_strings flattened -> HALT (never run blindly on an empty table)
EXIT_ROSTER_REGISTRY_MISSING = 26  # The entity row of that school is missing in table A / dept_name_variants is empty -> HALT for that school (never silently hit 0 with an empty whitelist)
EXIT_BYLINE_SCHEMA_FAIL = 27     # The byline_* table schema guard failed
EXIT_BYLINE_EMPTY_HITS_FAIL = 28 # The department-name whitelist hits 0 overall = a broken pipeline (never silently produce an empty table)
EXIT_BYLINE_YEAR_NULL_FAIL = 29  # publication_year is all null after the join (the year source is broken)

# --- preflight environment gate (30; numbers continue, do not collide with 12-29 and stay out of the 1-11 range) ---
#   Failure code of the preflight_env_check thin shell: a second preflight gate alongside the disk gate CAPACITY_GATE_FAIL(16),
#   which must be distinguishable from the disk gate (environment drift vs insufficient disk are two different pre-start HALTs).
#   The specific integer is an engineering convention (not an identification red line); U0 is the only issuer. New code.
ENVIRONMENT_GATE_FAIL = 30       # preflight environment gate (pyarrow pinned version / OpenAlex key / redlines SHA / rapidfuzz)

# --- U2 scale smoke gate (31; numbers continue, do not collide with 12-30 and stay out of the 1-11 range) ---
#   Failure code of the "real-data scale smoke" gate for U2: before a production run, an input scale
#   outside the operator-declared range (quadratic slowdown / ledger memory incidents are caught before the run starts) -> HALT.
#   Distinguishable from the disk gate (16) and the environment gate (30). The specific integer is an engineering
#   convention (not an identification red line); U0 is the only issuer. New code.
SCALE_GATE_FAIL = 31             # U2 preflight scale smoke gate (input table row count is outside the declared range)

# Range 1-11 is unassigned: it is not defined whether it belongs in the unified numbering table,
#   and whether the quota SystemExit(1) becomes a named constant is not defined either -> nothing is added here.
