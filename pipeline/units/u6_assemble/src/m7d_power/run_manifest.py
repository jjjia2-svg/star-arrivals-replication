"""run_manifest: end-to-end reproduction certificate seal (B6-RUNMANIFEST defined in this block;
schema to be absorbed into U0).

Hashes fall into two buckets:
  deterministic_artifacts: keys that must reproduce byte for byte from the same input (including the two frames' PK sha, D1);
  tolerance_artifacts:     observed values / tolerance keys (mde / golden observation / NA rate /
                           boundary flip count / lee_bounds_required).
+ reporting (5a/5b/5c/9/18) + expected_source_types (3-value vocabulary; a missing mapping raises).
The seal is written atomically with timestamps stripped, so the same input gives a byte-identical file (T57).
config_sha order invariant: a pinned list fed to the merkle in lexicographic order, with no glob (T54).
"""
from __future__ import annotations

import hashlib
import json
import pathlib

from common.atomic_io import atomic_write_bytes
from common.manifest import PROVENANCE_KEYS, merkle_root, verify_provenance

EXPECTED_SOURCE_VOCAB: tuple = ("a-priori", "derived", "不可知")

_DET_REQUIRED = ("source_snapshot_merkle", "config_sha", "rule_version",
                 "stars_set_hash", "env_lock_sha", "stage_shas",
                 "analysis_frame_p01_pk_sha256", "analysis_frame_p05_pk_sha256",
                 "G_treated_1pct", "G_treated_5pct", "golden_structural_pass",
                 "provenance_quad")
_TOL_REQUIRED = ("mde_1pct", "mde_5pct", "golden_works_count_observed",
                 "golden_arrival_year_observed", "golden_observed_in_range",
                 "golden_anchored_release", "golden_topics_version",
                 "boundary_sensitive_flip_count", "na_rate_fwci_frac",
                 "lee_bounds_required")


def config_sha_of(paths) -> str:
    """Pinned list + lexicographic order by file name -> merkle (order invariant; changes if content changes)."""
    ordered = sorted(pathlib.Path(p) for p in paths)
    return merkle_root([p.read_bytes() for p in ordered])


def verify_provenance_quad(artifact_headers: dict, pins: dict) -> None:
    """Pre-seal 4-tuple verifier (HIGH-7): verify artifact by artifact; any mismatch raises."""
    for name, header in artifact_headers.items():
        expected = pins.get(name)
        if expected is None:
            from common.manifest import ProvenanceMismatch

            raise ProvenanceMismatch(f"seal check: no pins for {name!r}", key=name)
        verify_provenance(header, {k: expected[k] for k in PROVENANCE_KEYS})


def seal_run_manifest(path, *, deterministic: dict, tolerance: dict,
                      reporting: dict, expected_source_types: dict) -> bytes:
    for k in _DET_REQUIRED:
        if k not in deterministic:
            raise ValueError(f"deterministic_artifacts missing key {k!r}")
    for k in _TOL_REQUIRED:
        if k not in tolerance:
            raise ValueError(f"tolerance_artifacts missing key {k!r}")
    # expected_source_types: every artifact has a key + every value is in the 3-value vocabulary
    need_types = {"analysis_frame_p01", "analysis_frame_p05", "star_set",
                  "events", "dose_p01", "dose_p05", "output",
                  "source_snapshot_merkle"}
    missing = need_types - set(expected_source_types)
    if missing:
        raise ValueError(f"expected_source_types mapping missing: "
                         f"{sorted(missing)}")
    for k, v in expected_source_types.items():
        if v not in EXPECTED_SOURCE_VOCAB:
            raise ValueError(
                f"expected_source_types[{k!r}]={v!r} not in the 3-value vocab "
                f"{EXPECTED_SOURCE_VOCAB}")
    doc = {
        "deterministic_artifacts": deterministic,
        "tolerance_artifacts": tolerance,
        "reporting": reporting,
        "expected_source_types": expected_source_types,
    }
    blob = json.dumps(doc, ensure_ascii=False, sort_keys=True,
                      indent=1).encode("utf-8")
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, blob)
    return blob
