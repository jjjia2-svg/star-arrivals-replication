"""U3 panel red lines / sentinel constants.

★U3 does not touch the identification layer (no arrival decisions / no star decisions / no re-doing disambiguation), so it has NO
  U2-style null→RedlineUnsigned threshold knob.
  POP_MIN_DISTINCT_YEARS=2 is the value of rule #9 (a sample-construction default, not an identification red line); it is written directly, not left null.
  The only null key in redlines.yaml that matters here is the upstream reconcile.diff_tolerance, which U3 bypasses by explicitly passing 0 in R1.
"""

# ── Population threshold rule ── #9 ────────────────────────────────────────────
# Rule: a single rule = "publications in the window (2000-2025) span >=2 distinct years"; the redundant >=1 paper rule is dropped.
# Status: a sample-construction default, **not an identification red line** (#9 is explicit about this).
#       Rationale (#9): the main line i<->star does not depend on a high threshold; ">=2 distinct years" screens out exactly the
#       single-paper / single-year noise that over-merges stick to most easily = reinforces disambiguation red line #1 in the same direction. Source: inclusion criteria used in the literature (10 sources).
POP_MIN_DISTINCT_YEARS = 2

# Optional robustness tier (for reviewer follow-up questions, not the main path; no pile of robustness checks, at most an optional >=3 papers).
# Not enabled by default; used only in sensitivity tables. Note: POP_MIN_WORKS=1 is not used (redundant lower bound).
POP_MIN_WORKS_SENSITIVITY = 3

# ── sentinel (not a red line; a deterministic engineering placeholder) ─────────────────────────────────────────
# Placeholder for PANEL.primary_affil_id when a year has no resolvable education-canonical primary affiliation.
# Semantics = "no resolvable education primary affiliation", **not** "no Australian affiliation".
PANEL_AFFIL_NONE = "AFFIL_NONE"

# Placeholder for raw_inst_id / canonical_affil_id of affil_timeline rows with institution_id=None.
# raw-only rows (HIGH-11 long-tail fragments; a single-paper fragment of Yves Zenou without ORCID is of this kind) use it, never silently dropped.
NONE_INST_SENTINEL = "__NONE__"
