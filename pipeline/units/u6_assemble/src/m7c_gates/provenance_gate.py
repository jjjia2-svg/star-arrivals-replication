"""provenance_gate (G-prov): HIGH-7. The 4-tuple in each frozen artifact header must be == one by one; any mismatch HALTs.

Object set (H7 closing): star_set / events / dose_p01 / dose_p05 / output, five artifacts.
Excluded: fwci_baseline (DAG-only, and blanking stars_set_hash would give a false HALT) + embeddings
(provenance not registered) + groups_ABC (produced by this unit itself).
Double anchor: u4 = the u4_ship anchor (star_set/events) + u5 = the u5_ship anchor (dose/output);
the three shared keys (source_snapshot_merkle / stars_set_hash / rule_version) must agree across anchors,
and config_sha is independent per unit. The comparison reads only stored values and never recomputes the merkle.
"""
from __future__ import annotations

from common.manifest import PROVENANCE_KEYS, ProvenanceMismatch, \
    verify_provenance

GPROV_OBJECTS: tuple = ("star_set", "events", "dose_p01", "dose_p05", "output")
GPROV_EXCLUDED: tuple = ("fwci_baseline", "embeddings", "groups_ABC")

_SHARED_ANCHOR_KEYS: tuple = ("source_snapshot_merkle", "stars_set_hash",
                              "rule_version")


def assert_cross_anchor_consistent(u4_quad: dict, u5_quad: dict) -> None:
    """The three shared keys of the double anchor must be equal (config_sha is independent per unit and may differ)."""
    for k in _SHARED_ANCHOR_KEYS:
        if u4_quad.get(k) != u5_quad.get(k):
            raise ProvenanceMismatch(
                f"shared key {k!r} differs between the two anchors: u4={u4_quad.get(k)!r} "
                f"u5={u5_quad.get(k)!r} — the upstream freezes come from different sources, HALT", key=k)


def run_provenance_gate(artifact_headers: dict, expected_by_artifact: dict) \
        -> dict:
    """verify_provenance artifact by artifact (missing header / missing key / mismatch -> ProvenanceMismatch HALT)."""
    checked = []
    for name in GPROV_OBJECTS:
        header = artifact_headers.get(name)
        if header is None:
            raise ProvenanceMismatch(
                f"artifact {name!r} has no manifest header — its source cannot be proven, HALT",
                key="manifest_header")
        expected = expected_by_artifact.get(name)
        if expected is None:
            raise ProvenanceMismatch(
                f"artifact {name!r} has no expected provenance quadruple (anchor not wired) — HALT", key="expected")
        verify_provenance(header, {k: expected[k] for k in PROVENANCE_KEYS})
        checked.append(name)
    return {"gate": "G-prov", "verdict": "PASS", "checked": checked,
            "excluded": list(GPROV_EXCLUDED)}
