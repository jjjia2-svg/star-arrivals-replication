"""reporting_fields: GLOBAL/PRIBA 5a/5b/5c/9/18.

Values are extracted from existing on-disk artifacts (official-doc-first: read local artifacts, not a live API);
a missing item is explicitly marked "MISSING — author follow-up" and never silently left blank.
  5a = sample size (frame rows / triples / events / departments)  <- this run's products
  5b = data snapshot version (source_snapshot_merkle)             <- upstream frozen header passed through (written by U1)
  5c = data source / API version note                             <- U1 snapshot_manifest passed through (MISSING if absent)
  9  = runtime environment (python/pyarrow versions)              <- env
  18 = software stack versions (rule_version + key packages)      <- redlines + env
"""
from __future__ import annotations

import sys

MISSING = "MISSING — author follow-up"


def collect_reporting(*, frame_stats: dict, source_snapshot_merkle: str,
                      rule_version: str, snapshot_api_note: str | None = None) \
        -> dict:
    import pyarrow

    return {
        "5a": frame_stats or MISSING,
        "5b": source_snapshot_merkle or MISSING,
        "5c": snapshot_api_note if snapshot_api_note else MISSING,
        "9": f"python {sys.version.split()[0]}; pyarrow {pyarrow.__version__}",
        "18": f"rule_version={rule_version}; pyarrow={pyarrow.__version__}",
    }
