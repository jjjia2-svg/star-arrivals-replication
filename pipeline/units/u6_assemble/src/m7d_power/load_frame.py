"""load_frame: read-only mount of the frame: schema validation + sole-producer invariant.

HIGH-1: m7d reads only the frozen artifact; the PK it reads must == the m7b sidecar (B6-MANIFEST-SIDECAR),
and drift raises SoleProducerDrift. This module never joins and never changes data.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pyarrow.parquet as pq

from common.schema import ANALYSIS_FRAME, assert_matches_schema
from identity.exit_codes import STRUCTURAL_GATE_FAIL

_PK = ("incumbent_person_id", "year", "star_person_id", "event_id")


class SoleProducerDrift(Exception):
    """The frame m7d reads disagrees with the m7b sidecar (sole-producer invariant violated)."""

    exit_code: int = STRUCTURAL_GATE_FAIL


def load_frame(out_root, p_level: str) -> list:
    out_root = pathlib.Path(out_root)
    t = pq.read_table(out_root / "frame" / "_frozen"
                      / f"analysis_frame_{p_level}.parquet")
    assert_matches_schema(t.schema.names, ANALYSIS_FRAME,
                          label=f"m7d_frame_{p_level}")
    rows = t.to_pylist()
    blob = "\n".join("|".join(str(r[k]) for k in _PK) for r in rows)
    pk_sha = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    sc = json.loads((out_root / "frame"
                     / f"analysis_frame_{p_level}._manifest.json")
                    .read_text(encoding="utf-8"))
    if sc["pk_sha256"] != pk_sha or sc["row_count"] != len(rows):
        raise SoleProducerDrift(
            f"{p_level}: m7d read PK != m7b sidecar "
            f"({pk_sha[:8]}… vs {sc['pk_sha256'][:8]}…)")
    return rows
