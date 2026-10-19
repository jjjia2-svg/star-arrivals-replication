"""m5b_aggregate — U5 M5b output-aggregation sub-block (drop star-co-authored works, pure aggregation -> two named OUTPUT tables).

Modules:
  star_coauthored_works — exclusion set (star_set is the single source, shipped-set definition, whole history is excluded, #8)
  aggregate             — feeding layer (the aggregation formula lives only in u0 identity/output_rule, to prevent B5)
  quality               — quality fill (#3+4: field-normalised ratio, no winsorisation)
  run_m5b               — orchestration and write (both tables from the same source #1 + single-source exclusion #44 + six-key tally)
"""
