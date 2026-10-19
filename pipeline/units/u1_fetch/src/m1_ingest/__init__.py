"""U1 M1 — snapshot -> derived-table writer subpackage (M1 ingest).

M1 streams the snapshot .gz shards (common.snapshot_reader.iter_jsonl_gz_shards),
probes fields (a missing required key -> EXIT_FIELDS_MISSING=19), and deterministically writes the derived
parquet tables (INSTITUTIONS / works_affil / authorship_edges etc.) through HashBucketWriter
to DATA_ROOT/u1_fetch/.
Skeleton placeholder — implementation pending.
"""
