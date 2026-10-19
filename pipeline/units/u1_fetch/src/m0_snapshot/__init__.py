"""U1 M0 — OpenAlex snapshot sync subpackage (M0-1..M0-3).

M0 syncs the raw .gz shards of works/authors/institutions/sources from the official S3
(s3://openalex/data/jsonl/) to the local SSD snapshot/ directory, validates the top-level manifest.json
(entities[].files[]), and passes the disk-capacity gate (preflight.disk_gate_decision).
Skeleton placeholder — implementation pending.
"""
